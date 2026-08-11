"""Ekspor data penjualan ke file Excel (.xlsx).

File berisi 2 sheet:
- "Struk" : satu baris per struk (merchant, tanggal, total, metode bayar, ...)
- "Item"  : rincian item dari semua struk (produk, qty, harga, ...)
"""
from __future__ import annotations

import io

import pandas as pd
from openpyxl.utils import get_column_letter

from . import database as db

_SHEET_RECEIPTS = "Struk"
_SHEET_ITEMS = "Item"

# Kolom yang ramah dibaca manusia (urutan tetap) untuk sheet Struk
_RECEIPT_COLUMNS = [
    ("id", "ID"),
    ("source", "Sumber"),
    ("sender_id", "Pengirim"),
    ("merchant", "Toko"),
    ("receipt_date", "Tanggal"),
    ("receipt_time", "Jam"),
    ("subtotal", "Subtotal"),
    ("tax", "Pajak"),
    ("total", "Total"),
    ("payment_method", "Metode Bayar"),
    ("ocr_confidence", "Akurasi OCR"),
    ("status", "Status"),
    ("created_at", "Dicatat Pada"),
]

# Kolom sheet Item
_ITEM_COLUMNS = [
    ("receipt_id", "ID Struk"),
    ("name", "Nama Produk"),
    ("qty", "Qty"),
    ("unit_price", "Harga Satuan"),
    ("total_price", "Total Harga"),
]


def _apply_columns(df: pd.DataFrame, columns: list[tuple[str, str]]) -> pd.DataFrame:
    """Pilih + urutkan kolom dan beri nama Indonesia; tambah kolom yang belum ada."""
    for key, label in columns:
        if key not in df.columns:
            df[key] = None
    df = df[[k for k, _ in columns]].copy()
    df.columns = [label for _, label in columns]
    return df


def build_xlsx() -> bytes:
    """Buat file .xlsx dalam memori. Mengembalikan bytes file Excel."""
    receipts = db.query("SELECT * FROM receipts ORDER BY id")
    items = db.query("SELECT * FROM items ORDER BY receipt_id, id")

    df_receipts = _apply_columns(pd.DataFrame(receipts), _RECEIPT_COLUMNS)
    df_items = _apply_columns(pd.DataFrame(items), _ITEM_COLUMNS)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_receipts.to_excel(writer, sheet_name=_SHEET_RECEIPTS, index=False)
        df_items.to_excel(writer, sheet_name=_SHEET_ITEMS, index=False)

        # Lebar kolom otomatis agar enak dibaca di Excel
        for sheet_name, df in ((_SHEET_RECEIPTS, df_receipts), (_SHEET_ITEMS, df_items)):
            ws = writer.sheets[sheet_name]
            for i, col in enumerate(df.columns, start=1):
                lengths = [len(str(v)) for v in df[col].head(200) if pd.notna(v)]
                width = max([len(str(col))] + lengths)
                ws.column_dimensions[get_column_letter(i)].width = min(width + 2, 40)

    return buf.getvalue()


def export_filename() -> str:
    """Nama file default untuk unduhan, mis. penjualan_2026-08-11.xlsx."""
    return f"penjualan_{db.today_iso()}.xlsx"
