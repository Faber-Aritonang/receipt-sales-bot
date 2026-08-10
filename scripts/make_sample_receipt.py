#!/usr/bin/env python3
"""Buat struk belanja contoh (sintetis) untuk menguji pipeline OCR.

Cara pakai:
    python scripts/make_sample_receipt.py            # simpan ke data/sample_struk.png
    python scripts/make_sample_receipt.py out.png    # simpan ke path lain
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LINES = [
    "TOKO MURAH JAYA",
    "Jl. Merdeka No. 12, Bandung",
    "Telp: 022-5551234  NPWP: 01.234.567.8-9",
    "-" * 30,
    "10/08/2026 14:32",
    "-" * 30,
    "Beras Premium 5kg   2 x 75000",
    "Gula Pasir 1kg      14500",
    "Minyak Goreng 2L    21000",
    "Telur Ayam 1kg      28000",
    "Susu UHT 1L         18500",
    "-" * 30,
    "SUBTOTAL            232000",
    "PPN 11%             25520",
    "TOTAL               257520",
    "TUNAI               260000",
    "KEMBALI             2480",
    "-" * 30,
    "Terima kasih!",
]


def font(size: int):
    for name in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main(out_path: str = None) -> None:
    out = Path(out_path) if out_path else Path(__file__).resolve().parent.parent / "data" / "sample_struk.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    f = font(17)
    pad = 14
    line_h = 24
    width = 330
    height = pad * 2 + line_h * len(LINES)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(LINES):
        draw.text((pad, pad + i * line_h), line, fill="black", font=f)
    img.save(out)
    print(f"Struk contoh tersimpan: {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
