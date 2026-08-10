"""Konfigurasi aplikasi — dibaca dari file .env (lihat .env.example).

Jika Tesseract tidak terinstall di sistem (mis. butuh sudo), aplikasi
otomatis memakai salinan lokal di folder `vendor/tesseract/`.
"""
import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- Data (SQLite + folder upload) ----
DATA_DIR = os.path.abspath(os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data")))
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.environ.get("DB_PATH", os.path.join(DATA_DIR, "sales.db"))
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# ---- Telegram ----
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ALLOWED_IDS = {
    int(x.strip())
    for x in os.environ.get("TELEGRAM_ALLOWED_IDS", "").split(",")
    if x.strip().lstrip("-").isdigit()
}

# ---- WhatsApp bridge (Node.js) ----
BRIDGE_URL = os.environ.get("BRIDGE_URL", "http://127.0.0.1:3100").rstrip("/")
BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "3100"))
BRIDGE_WEBHOOK_SECRET = os.environ.get("BRIDGE_WEBHOOK_SECRET", "ganti-ini-dengan-string-acak")

# ---- Server API / Dashboard ----
API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8000"))

# ---- OCR (Tesseract) ----
import shutil

# 1) Nilai eksplisit dari .env
TESSERACT_CMD = os.environ.get("TESSERACT_CMD", "").strip()
TESSDATA_PREFIX = os.environ.get("TESSDATA_PREFIX", "").strip()
OCR_LANG = os.environ.get("OCR_LANG", "ind+eng")

# "tesseract" di .env = pakai tesseract sistem; jika tidak ada di PATH, fallback ke vendor
if TESSERACT_CMD == "tesseract" and not shutil.which("tesseract"):
    TESSERACT_CMD = ""
if TESSDATA_PREFIX and not os.path.isdir(TESSDATA_PREFIX):
    TESSDATA_PREFIX = ""

# 2) Fallback: salinan vendor di dalam project (tanpa sudo)
_VENDOR_TESS = os.path.join(BASE_DIR, "vendor", "tesseract")
_VENDOR_BIN = os.path.join(_VENDOR_TESS, "usr", "bin", "tesseract")
if (not TESSERACT_CMD or TESSERACT_CMD == "tesseract") and os.path.exists(_VENDOR_BIN):
    TESSERACT_CMD = _VENDOR_BIN
    if not TESSDATA_PREFIX:
        _d = os.path.join(_VENDOR_TESS, "usr", "share", "tesseract-ocr", "5", "tessdata")
        TESSDATA_PREFIX = _d if os.path.isdir(_d) else ""
    _lib_dirs = [
        os.path.join(_VENDOR_TESS, "usr", "lib", "x86_64-linux-gnu"),
        os.path.join(_VENDOR_TESS, "usr", "lib"),
    ]
    _existing = [d for d in _lib_dirs if os.path.isdir(d)]
    if _existing:
        old = os.environ.get("LD_LIBRARY_PATH", "")
        os.environ["LD_LIBRARY_PATH"] = ":".join(_existing + ([old] if old else []))

if TESSDATA_PREFIX:
    os.environ["TESSDATA_PREFIX"] = TESSDATA_PREFIX
