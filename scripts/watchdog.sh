#!/bin/bash
# ============================================================================
# Watchdog Sales Canvas Bot — auto-restart server API & bridge WhatsApp.
#
# Cara pakai:
#   setsid nohup bash scripts/watchdog.sh > /tmp/watchdog.log 2>&1 < /dev/null &
#
# Memantau tiap 20 detik:
#   - API Python  : proses run.py hidup? (port 8000)
#   - Bridge WA   : proses node index.js hidup? (port 3100)
# Bila mati -> restart otomatis + catat ke log. Jangan dijalankan lebih dari
# satu instance sekaligus (pakai flock agar aman).
# ============================================================================
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG=/tmp/watchdog.log
CHECK_INTERVAL=20
# lockfile agar hanya satu watchdog yang berjalan
LOCK=/tmp/watchdog.lock

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[watchdog] instance lain sudah berjalan — keluar." >> "$LOG"
  exit 0
fi

log() { echo "[watchdog] $(date '+%F %T') $*" >> "$LOG"; }

# ---------------------------------------------------------------------------
# Notifikasi restart via Telegram (opsional).
# Membaca dari .env root:
#   - TELEGRAM_BOT_TOKEN      (wajib)
#   - WATCHDOG_NOTIFY_CHAT_ID (chat id tujuan; kalau kosong fallback ke
#                              TELEGRAM_ALLOWED_IDS yang pertama)
# Tidak ada token/chat id -> notifikasi dilewati dengan tenang.
# ---------------------------------------------------------------------------
TG_TOKEN=""
TG_CHAT=""
if [ -f "$ROOT/.env" ]; then
  TG_TOKEN="$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ROOT/.env" | head -1 | cut -d= -f2- | tr -d '"\r')"
  TG_CHAT="$(grep -E '^WATCHDOG_NOTIFY_CHAT_ID=' "$ROOT/.env" | head -1 | cut -d= -f2- | tr -d '"\r')"
  if [ -z "$TG_CHAT" ]; then
    TG_CHAT="$(grep -E '^TELEGRAM_ALLOWED_IDS=' "$ROOT/.env" | head -1 | cut -d= -f2- | cut -d, -f1 | tr -d '"\r')"
  fi
fi

notify_telegram() {
  local msg="$1"
  if [ -z "$TG_TOKEN" ] || [ -z "$TG_CHAT" ]; then
    return 0
  fi
  curl -sf -m 10 -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TG_CHAT}" \
    --data-urlencode "text=${msg}" > /dev/null 2>&1
}

start_api() {
  cd "$ROOT" || return 1
  setsid nohup .venv/bin/python run.py > /tmp/api_live.log 2>&1 < /dev/null &
  local pid=$!
  log "API di-restart (PID $pid)"
  notify_telegram "⚠️ *Sales Canvas* — server API di-restart otomatis oleh watchdog (PID $pid)."
}

start_bridge() {
  cd "$ROOT/whatsapp-bridge" || return 1
  setsid nohup node index.js > /tmp/bridge_live.log 2>&1 < /dev/null &
  local pid=$!
  log "bridge WhatsApp di-restart (PID $pid)"
  notify_telegram "⚠️ *Sales Canvas* — bridge WhatsApp di-restart otomatis oleh watchdog (PID $pid)."
}

# ---------------------------------------------------------------------------
# Guard Tesseract: bersihkan proses OCR yang macet / menumpuk.
#
# Tiap foto memunculkan beberapa proses tesseract. Normalnya selesai dalam
# hitungan detik dan dibatasi OCR_MAX_CONCURRENCY=1 (jadi maksimal ~1-2 proses
# hidup). Bila ada proses yang hidup lebih lama dari batas timeout OCR
# (OCR_TIMEOUT=90s) atau jumlahnya melonjak, itu tanda tesseract macet dan
# membuat bot "hang" — bunuh yang tertua sampai normal kembali.
# ---------------------------------------------------------------------------
TESS_MAX_AGE=150   # detik: lebih tua dari ini = macet (OCR_TIMEOUT 90s + margin)
TESS_MAX_COUNT=4   # lebih banyak dari ini = menumpuk (normalnya 1-2)

# "mm:ss" / "hh:mm:ss" / "dd-hh:mm:ss" -> total detik
_etime_seconds() {
  local e="$1" days=0 h=0 m=0 s=0 rest=""
  if [[ "$e" == *-* ]]; then
    days="${e%%-*}"
    e="${e#*-}"
  fi
  if [[ "$e" == *:*:* ]]; then
    h="${e%%:*}"
    rest="${e#*:}"
    m="${rest%%:*}"
    s="${rest#*:}"
  else
    m="${e%%:*}"
    s="${e#*:}"
  fi
  echo $((days * 86400 + h * 3600 + m * 60 + s))
}

clean_stuck_tesseract() {
  # kumpulkan (detik_umur, pid), urutkan umur tertua dulu
  local entries=""
  while read -r pid etime; do
    [ -z "$pid" ] && continue
    local secs; secs=$(_etime_seconds "$etime")
    entries+="$secs $pid\n"
  done < <(ps -eo pid=,etime=,comm= | awk '$3=="tesseract" {print $1, $2}')

  [ -z "$entries" ] && return 0

  local line secs pid count=0 killed=0
  while read -r line; do
    [ -z "$line" ] && continue
    secs="${line%% *}"
    pid="${line##* }"
    count=$((count + 1))
    if [ "$secs" -gt "$TESS_MAX_AGE" ] || [ "$count" -gt "$TESS_MAX_COUNT" ]; then
      kill -9 "$pid" 2>/dev/null && killed=$((killed + 1))
    fi
  done < <(printf "%b" "$entries" | sort -rn)

  if [ "$killed" -gt 0 ]; then
    log "tesseract macet/menumpuk ($count proses) -> $killed dibunuh"
    notify_telegram "⚠️ *Sales Canvas* — ${killed} proses tesseract macet dibunuh watchdog (total ${count})."
  fi
}

log "watchdog dimulai (interval ${CHECK_INTERVAL}s) di $ROOT"

while true; do
  # --- API: cek proses dulu, lalu health port 8000 ---
  if ! pgrep -f 'python run.py' > /dev/null 2>&1; then
    log "API tidak berjalan -> restart"
    start_api
  elif ! curl -sf -m 5 http://127.0.0.1:8000/api/health > /dev/null 2>&1; then
    log "API tidak merespons (port 8000) -> restart"
    pkill -9 -f 'python run.py' 2>/dev/null
    sleep 1
    start_api
  fi

  # --- bridge WhatsApp: cek proses dulu, lalu health port 3100 ---
  if ! pgrep -f 'node index.js' > /dev/null 2>&1; then
    log "bridge tidak berjalan -> restart"
    start_bridge
  elif ! curl -sf -m 5 http://127.0.0.1:3100/health > /dev/null 2>&1; then
    log "bridge tidak merespons (port 3100) -> restart"
    pkill -9 -f 'node index.js' 2>/dev/null
    sleep 1
    start_bridge
  fi

  # --- tesseract: bunuh proses OCR yang macet / menumpuk (sebelum bikin hang) ---
  clean_stuck_tesseract

  sleep "$CHECK_INTERVAL"
done
