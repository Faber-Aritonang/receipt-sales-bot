#!/bin/bash
# ============================================================================
# Uji end-to-end otomatis Sales Canvas Bot.
#
# Memverifikasi seluruh rantai layanan masih sehat:
#   1. server API hidup (port 8000)
#   2. bridge WhatsApp hidup (port 3100)
#   3. dashboard terkunci (302 tanpa login)
#   4. perintah bot (text) -> balasan laporan via webhook WhatsApp
#   5. foto struk (image)  -> OCR -> tersimpan di DB -> balasan "Struk tersimpan"
#   6. watchdog systemd aktif
#
# Cara pakai:  bash scripts/e2e_test.sh
# Exit code 0 = semua lolos; 1 = ada yang gagal.
# ============================================================================
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PASS=0
FAIL=0
# baca dari config Python — cara paling andal & konsisten dengan server
SECRET="$("$ROOT/.venv/bin/python" -c "from app import config; print(config.BRIDGE_WEBHOOK_SECRET)" 2>/dev/null)"
API=http://127.0.0.1:8000
BRIDGE=http://127.0.0.1:3100
NOW="$(date '+%Y-%m-%d %H:%M:%S')"

# Uji OCR mengirim ke server live (memakai DB asli). Untuk membaca jumlah
# struk, gunakan env sementara supaya tidak menyentuh data produksi saat
# meng-import modul database.
E2E_DATA="$(mktemp -d)"
export DATA_DIR="$E2E_DATA"
export DB_PATH="$E2E_DATA/e2e.db"
export UPLOAD_DIR="$E2E_DATA/uploads"
PY() { DATA_DIR="$E2E_DATA" DB_PATH="$E2E_DATA/e2e.db" UPLOAD_DIR="$E2E_DATA/uploads" "$ROOT/.venv/bin/python" "$@"; }

ok()   { PASS=$((PASS + 1)); echo "  ✅ $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  ❌ $1"; }

check() { # check <nama> <status_kode_harapan> <hasil_curl_dengan_-o_dan_-w>
  local name="$1" expect="$2" got="$3"
  if [ "$got" = "$expect" ]; then ok "$name (HTTP $got)"; else fail "$name (harus $expect, dapat $got)"; fi
}

echo "═══════════════════════════════════════════════════════"
echo "  E2E TEST — Sales Canvas Bot   ($NOW)"
echo "═══════════════════════════════════════════════════════"

# --- 1. server API ---
echo; echo "── 1. Server API ──"
CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$API/api/health")
check "API /api/health" "200" "$CODE"

# --- 2. bridge WhatsApp ---
echo; echo "── 2. Bridge WhatsApp ──"
CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$BRIDGE/health")
check "bridge /health" "200" "$CODE"

# --- 3. dashboard terkunci ---
echo; echo "── 3. Dashboard (proteksi) ──"
# tanpa -L: kita ingin melihat kode ASLI (302 = butuh login), bukan mengikuti
# redirect ke halaman login (yang selalu 200).
CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$API/dashboard")
if [ "$CODE" = "200" ]; then
  ok "dashboard dapat diakses (tanpa password = terbuka)"
else
  check "dashboard tanpa login (302 = terkunci)" "302" "$CODE"
fi

# --- 4. perintah teks -> laporan ---
echo; echo "── 4. Perintah bot (webhook WhatsApp) ──"
if [ -n "$SECRET" ]; then
  REPLY=$(curl -s -m 15 -X POST "$API/api/whatsapp/inbound" \
    -F "sender=e2e@lid" -F "type=text" -F "text=1.laporan harian" \
    -F "secret=$SECRET" | "$ROOT/.venv/bin/python" -c "import json,sys; print(json.load(sys.stdin).get('reply',''))" 2>/dev/null)
  case "$REPLY" in
    *"LAPORAN HARIAN"*) ok "perintah '1.laporan harian' -> LAPORAN HARIAN" ;;
    *) fail "perintah '1.laporan harian' tidak membalas laporan: ${REPLY:0:60}" ;;
  esac
else
  fail "BRIDGE_WEBHOOK_SECRET kosong di .env — lewati uji perintah"
fi

# --- 5. foto struk -> OCR -> DB ---
echo; echo "── 5. Foto struk (OCR → DB) ──"
SAMPLE="$ROOT/data/sample_struk.png"
if [ ! -f "$SAMPLE" ]; then
  "$ROOT/.venv/bin/python" "$ROOT/scripts/make_sample_receipt.py" > /dev/null 2>&1
fi
if [ -f "$SAMPLE" ] && [ -n "$SECRET" ]; then
  # jumlah struk asli di DB PRODUKSI (sebelum & sesudah)
  BEFORE=$("$ROOT/.venv/bin/python" -c "from app import database as db; print(db.count_receipts())" 2>/dev/null)
  REPLY=$(curl -s -m 60 -X POST "$API/api/whatsapp/inbound" \
    -F "sender=e2e@lid" -F "type=image" -F "caption=struk uji e2e" \
    -F "secret=$SECRET" -F "image=@$SAMPLE;type=image/png" \
    | "$ROOT/.venv/bin/python" -c "import json,sys; print(json.load(sys.stdin).get('reply',''))" 2>/dev/null)
  AFTER=$("$ROOT/.venv/bin/python" -c "from app import database as db; print(db.count_receipts())" 2>/dev/null)
  if echo "$REPLY" | grep -q "Struk tersimpan"; then
    ok "foto struk diproses: \"${REPLY:0:45}…\""
    if [ "$AFTER" -gt "$BEFORE" ]; then
      ok "DB bertambah ($BEFORE → $AFTER struk)"
      # bersihkan struk uji dari DB produksi (hapus receipt + item-nya)
      RID=$(echo "$REPLY" | grep -oE '#[0-9]+' | head -1 | tr -d '#')
      if [ -n "$RID" ]; then
        "$ROOT/.venv/bin/python" - "$RID" <<'PY'
import sys
from app import database as db
with db.get_conn() as conn:
    conn.execute("DELETE FROM items WHERE receipt_id=?", (sys.argv[1],))
    conn.execute("DELETE FROM receipts WHERE id=?", (sys.argv[1],))
print(f"struk uji #{sys.argv[1]} dihapus dari DB produksi")
PY
      fi
    else
      fail "DB tidak bertambah ($BEFORE → $AFTER) walau OCR sukses"
    fi
  else
    fail "foto struk tidak tersimpan: ${REPLY:0:70}"
  fi
else
  fail "sampel struk tidak ada & secret kosong — lewati uji foto"
fi

# --- 6. watchdog systemd ---
echo; echo "── 6. Watchdog (systemd) ──"
if systemctl --user is-active sales-watchdog.service > /dev/null 2>&1; then
  ok "service sales-watchdog aktif (systemd)"
else
  fail "sales-watchdog.service tidak aktif"
fi

echo
rm -rf "$E2E_DATA"  # bersihkan DB sementara

echo "═══════════════════════════════════════════════════════"
echo "  HASIL: $PASS lolos, $FAIL gagal"
echo "═══════════════════════════════════════════════════════"
[ "$FAIL" -eq 0 ]
