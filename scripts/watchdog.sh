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

  sleep "$CHECK_INTERVAL"
done
