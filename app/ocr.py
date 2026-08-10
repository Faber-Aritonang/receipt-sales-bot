"""Pipeline OCR: preprocessing OpenCV -> Tesseract (bahasa Indonesia).

Mencoba beberapa mode segmentasi (PSM) dan memilih hasil terbaik
berdasarkan skor "struk-ness" (banyak kata kunci + angka).
"""
from __future__ import annotations

import io
import os
import re
from functools import lru_cache

import cv2
import numpy as np
import pytesseract
from PIL import Image

from . import config

if config.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD

_TESS_EXTRA = f"--tessdata-dir {config.TESSDATA_PREFIX}" if config.TESSDATA_PREFIX else ""

# Kata kunci yang menandakan teks berasal dari struk belanja
_KEYWORDS = re.compile(
    r"\b(TOTAL|SUBTOTAL|JUMLAH|BAYAR|TUNAI|DEBIT|KREDIT|QRIS|KEMBALI|"
    r"STRUK|CASHIER|KASIR|HARGA|ITEM|PCS|Rp)\b",
    re.IGNORECASE,
)


def _deskew(binary: np.ndarray) -> np.ndarray:
    """Perbaiki kemiringan teks kecil (±10 derajat) agar akurasi OCR naik."""
    coords = np.column_stack(np.where(binary > 0))
    if coords.size == 0:
        return binary
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    if abs(angle) < 0.5:
        return binary
    h, w = binary.shape
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(binary, matrix, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def preprocess(img_bgr: np.ndarray) -> np.ndarray:
    """Siapkan foto struk untuk Tesseract: grayscale, upscale 2x, binerisasi."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    # upscale 2x membantu OCR pada foto kamera
    gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 15
    )
    binary = _deskew(binary)
    return binary


def _score(text: str) -> int:
    """Skor: banyak kata kunci struk + jumlah angka + baris terbaca."""
    kw = len(_KEYWORDS.findall(text))
    digits = len(re.findall(r"\d", text))
    lines = len([l for l in text.splitlines() if l.strip()])
    return kw * 5 + min(digits, 200) + min(lines, 50)


def ocr_image(image_bytes: bytes) -> tuple[str, str]:
    """OCR foto struk. Mengembalikan (teks_terbaik, konfigurasi_yang_dipakai)."""
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return "", "gagal-decode"

    processed = preprocess(img)

    candidates: list[tuple[int, str, str]] = []
    for psm in (6, 3, 11):
        try:
            txt = pytesseract.image_to_string(
                processed, lang=config.OCR_LANG, config=f"--psm {psm} {_TESS_EXTRA}".strip()
            )
            candidates.append((_score(txt), txt, f"psm{psm}"))
        except Exception:  # pragma: no cover - tesseract runtime issue
            continue

    if not candidates:
        return "", "gagal-ocr"

    candidates.sort(key=lambda c: c[0], reverse=True)
    best_score, best_text, best_cfg = candidates[0]

    # Fallback: OCR langsung dari gambar asli (tanpa preprocessing)
    try:
        raw = pytesseract.image_to_string(
            img, lang=config.OCR_LANG, config=f"--psm 6 {_TESS_EXTRA}".strip()
        )
        if _score(raw) > best_score:
            return raw, "raw-psm6"
    except Exception:
        pass

    return best_text, best_cfg


@lru_cache(maxsize=1)
def language_packs_available() -> list[str]:
    """Daftar bahasa Tesseract yang tersedia di sistem."""
    import subprocess

    cmd = [pytesseract.pytesseract.tesseract_cmd, "--list-langs"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                         env=os.environ.copy()).stdout
    return [l.strip() for l in out.splitlines() if l.strip()]


def ocr_ready() -> bool:
    """Cek apakah tesseract + SEMUA bahasa yang dikonfigurasi siap dipakai.

    image_to_string(lang="ind+eng") butuh ind DAN eng ada, jadi periksa
    semuanya (bukan hanya salah satu).
    """
    try:
        langs = set(language_packs_available())
        configured = {l.split("+")[-1] for l in config.OCR_LANG.split("+")}
        return configured <= langs
    except Exception:
        return False


def bytes_to_png(image_bytes: bytes) -> bytes:
    """Normalisasi ke PNG agar tersimpan rapi di folder upload."""
    img = Image.open(io.BytesIO(image_bytes))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()
