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

start_api() {
  cd "$ROOT" || return 1
  setsid nohup .venv/bin/python run.py > /tmp/api_live.log 2>&1 < /dev/null &
  log "API di-restart (PID $!)"
}

start_bridge() {
  cd "$ROOT/whatsapp-bridge" || return 1
  setsid nohup node index.js > /tmp/bridge_live.log 2>&1 < /dev/null &
  log "bridge WhatsApp di-restart (PID $!)"
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
