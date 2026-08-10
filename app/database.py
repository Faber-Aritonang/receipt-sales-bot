"""Akses database SQLite: tabel receipts & items.

Skema:
- receipts : satu struk = satu baris (merchant, tanggal, total, metode bayar, ...)
- items    : rincian item dari setiap struk (produk terlaris dihitung dari sini)
"""
import sqlite3
from contextlib import closing
from datetime import datetime

import pandas as pd

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT NOT NULL,              -- 'telegram' | 'whatsapp'
    sender_id      TEXT NOT NULL,
    merchant       TEXT,
    receipt_date   TEXT,                       -- YYYY-MM-DD
    receipt_time   TEXT,                       -- HH:MM
    subtotal       REAL,
    tax            REAL,
    total          REAL,
    payment_method TEXT,
    image_path     TEXT,
    raw_text       TEXT,
    ocr_confidence TEXT,                       -- tinggi/sedang/rendah
    status         TEXT DEFAULT 'ok',
    created_at     TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id  INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    name        TEXT,
    qty         REAL DEFAULT 1,
    unit_price  REAL,
    total_price REAL
);

CREATE INDEX IF NOT EXISTS idx_receipts_date  ON receipts(receipt_date);
CREATE INDEX IF NOT EXISTS idx_items_receipt  ON items(receipt_id);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    with closing(get_conn()) as conn:
        conn.executescript(_SCHEMA)


def insert_receipt(receipt: dict, items: list[dict]) -> int:
    """Simpan satu struk beserta item-nya. Mengembalikan id struk."""
    with closing(get_conn()) as conn, conn:  # closing = tutup, conn = commit
        cur = conn.execute(
            """
            INSERT INTO receipts
                (source, sender_id, merchant, receipt_date, receipt_time,
                 subtotal, tax, total, payment_method, image_path, raw_text, ocr_confidence)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                receipt.get("source", "unknown"),
                receipt.get("sender_id", ""),
                receipt.get("merchant"),
                receipt.get("receipt_date"),
                receipt.get("receipt_time"),
                receipt.get("subtotal"),
                receipt.get("tax"),
                receipt.get("total"),
                receipt.get("payment_method"),
                receipt.get("image_path"),
                receipt.get("raw_text"),
                receipt.get("ocr_confidence"),
            ),
        )
        receipt_id = cur.lastrowid
        for it in items:
            conn.execute(
                """
                INSERT INTO items (receipt_id, name, qty, unit_price, total_price)
                VALUES (?,?,?,?,?)
                """,
                (
                    receipt_id,
                    it.get("name"),
                    it.get("qty", 1),
                    it.get("unit_price"),
                    it.get("total_price"),
                ),
            )
        return receipt_id


def query(sql: str, params: tuple = ()) -> list[dict]:
    with closing(get_conn()) as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    with closing(get_conn()) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def recent_receipts(limit: int = 20) -> list[dict]:
    return query(
        """
        SELECT * FROM receipts
        ORDER BY COALESCE(receipt_date || ' ' || COALESCE(receipt_time,''), created_at) DESC
        LIMIT ?
        """,
        (limit,),
    )


def count_receipts() -> int:
    return query("SELECT COUNT(*) AS c FROM receipts")[0]["c"]


def today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# Pastikan skema selalu tersedia begitu modul dipakai (aman dipanggil berulang)
init_db()
