#!/bin/bash
# ============================================================================
# Pasang watchdog Sales Canvas sebagai systemd USER service (auto-start saat boot).
#
# Prasyarat: linger user diaktifkan agar service tetap berjalan tanpa login:
#   loginctl enable-linger $USER
#
# Cara pakai:
#   bash scripts/install_watchdog_systemd.sh
# ============================================================================
set -e

# systemctl --user butuh XDG_RUNTIME_DIR; beri default bila kosong (mis. saat
# skrip dijalankan dari cron / sesi non-interaktif).
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/sales-watchdog.service"

mkdir -p "$UNIT_DIR"

# unit file dengan path absolut (ganti %h)
sed -e "s|%h|$HOME|g" "$ROOT/deploy/sales-watchdog.service" > "$UNIT"
echo "✅ unit file: $UNIT"

# hentikan watchdog manual (yang memakai flock) agar tidak dobel
echo "⏹  menghentikan watchdog manual (jika ada)..."
pkill -f 'scripts/watchdog.sh' 2>/dev/null || true
sleep 1

systemctl --user daemon-reload
systemctl --user enable --now sales-watchdog.service

echo
echo "--- status ---"
systemctl --user status sales-watchdog.service --no-pager | head -12
