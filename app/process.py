"""Pipeline bersama untuk Telegram & WhatsApp.

Alur foto struk: simpan gambar -> OCR -> parse -> simpan DB -> balas ringkasan.
Perintah laporan juga dipakai bersama oleh kedua platform.
"""
from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

from . import analytics, config, database as db, ocr, parser

HELP_TEXT = """🤖 *SALES CANVAS BOT*

Cara pakai:
1️⃣ Kirim *foto struk* — otomatis dibaca (OCR), disimpan ke database, lalu dirangkum.
2️⃣ Kirim perintah di bawah untuk melihat analisa:

📆 /laporanharian — penjualan hari ini
🗓️ /laporanmingguan — 7 hari terakhir
📅 /laporanbulanan — bulan ini + produk terlaris
🏆 /produkterlaris — 10 produk terlaris
💼 /total — ringkasan semua data
📥 /export — unduh seluruh data sebagai file Excel (.xlsx)
❓ /bantuan — bantuan ini

💡 Perintah juga bisa memakai garis bawah (mis. /laporan_harian).

📊 Dashboard web: http://localhost:8000/dashboard
"""

COMMANDS = {
    # perintah dapat diketik dengan atau tanpa garis bawah, keduanya dikenali
    "laporan_harian": "laporan_harian",
    "laporanharian": "laporan_harian",
    "laporan_mingguan": "laporan_mingguan",
    "laporanmingguan": "laporan_mingguan",
    "laporan_bulanan": "laporan_bulanan",
    "laporanbulanan": "laporan_bulanan",
    "produk_terlaris": "produk_terlaris",
    "produkterlaris": "produk_terlaris",
    "total": "total",
    "ringkasan": "total",
    "export": "export",
    "bantuan": "bantuan",
    "help": "bantuan",
    "menu": "bantuan",
    "tombol": "bantuan",
    "mulai": "bantuan",
    "start": "bantuan",
}

# pemetaan versi "dibersihkan" (tanpa _ / - / spasi) -> perintah kanonik
_NORM_COMMANDS = {re.sub(r"[_\-\s]+", "", k): v for k, v in COMMANDS.items()}

# angka menu fallback (sama dengan urutan tombol di bridge WhatsApp)
NUM_COMMANDS = {
    "1": "laporan_harian",
    "2": "laporan_mingguan",
    "3": "laporan_bulanan",
    "4": "produk_terlaris",
    "5": "total",
    "6": "export",
    "7": "bantuan",
}


def _save_image(image_bytes: bytes, source: str, sender_id: str) -> str:
    png = ocr.bytes_to_png(image_bytes)
    safe_sender = re.sub(r"[^A-Za-z0-9_@.\-]", "_", sender_id or "")[:32]
    fname = f"{source}_{safe_sender}_{uuid.uuid4().hex[:10]}.png"
    path = Path(config.UPLOAD_DIR) / fname
    path.write_bytes(png)
    return str(path)


def handle_image(image_bytes: bytes, source: str, sender_id: str) -> dict:
    """Proses satu foto struk. Mengembalikan dict {reply, data, success}."""
    t0 = time.time()
    image_path = _save_image(image_bytes, source, sender_id)

    if not ocr.ocr_ready():
        return {
            "success": False,
            "reply": (
                "⚠️ OCR (Tesseract) belum siap di sistem ini.\n"
                "Install dulu: `sudo apt install tesseract-ocr tesseract-ocr-ind`\n"
                "atau pastikan folder vendor/tesseract tersedia."
            ),
            "data": None,
        }

    raw_text, ocr_cfg = ocr.ocr_image(image_bytes)
    if not raw_text.strip():
        return {
            "success": False,
            "reply": "😕 Foto tidak terbaca. Coba foto ulang dengan cahaya cukup & struk rata.",
            "data": None,
        }

    parsed = parser.parse_receipt(raw_text)
    receipt_row = {
        "source": source,
        "sender_id": sender_id,
        "image_path": image_path,
        "raw_text": raw_text,
        "ocr_confidence": parsed["confidence"],
        "merchant": parsed["merchant"],
        "receipt_date": parsed["receipt_date"],
        "receipt_time": parsed["receipt_time"],
        "subtotal": parsed["subtotal"],
        "tax": parsed["tax"],
        "total": parsed["total"],
        "payment_method": parsed["payment_method"],
    }
    receipt_id = db.insert_receipt(receipt_row, parsed["items"])
    elapsed = time.time() - t0

    reply = build_receipt_reply(parsed, receipt_id, elapsed)
    return {"success": True, "reply": reply, "data": {"receipt_id": receipt_id, **parsed}}


def build_receipt_reply(p: dict, receipt_id: int, elapsed: float) -> str:
    emoji = {"tinggi": "✅", "sedang": "⚠️", "rendah": "🟠"}.get(p["confidence"], "⚠️")
    lines = [
        f"{emoji} *Struk tersimpan!* (#{receipt_id})",
        "",
        f"🏪 Toko: *{p['merchant'] or '—'}*",
        f"📅 Tanggal: {p['receipt_date'] or '—'}  🕐 {p['receipt_time'] or '—'}",
    ]
    if p["total"] is not None:
        lines.append(f"💰 Total: *Rp {p['total']:,.0f}*".replace(",", "."))
    lines.append(f"💳 Bayar: {p['payment_method'] or '—'}")
    if p["items"]:
        shown = p["items"][:4]
        lines.append("")
        lines.append("🛒 *Item:*")
        for it in shown:
            qty = f"{it['qty']:g}x " if it["qty"] != 1 else ""
            lines.append(f"• {qty}{it['name']} — Rp {it['total_price']:,.0f}".replace(",", "."))
        if len(p["items"]) > 4:
            lines.append(f"  …dan {len(p['items']) - 4} item lainnya")
    lines.append("")
    lines.append(f"⚙️ OCR {elapsed:.1f}s · akurasi {p['confidence']}")
    lines.append("")
    lines.append("Perintah /bantuan untuk daftar laporan. 📊")
    return "\n".join(lines)


def command_reply(text: str, sender_id: str = "") -> str:
    """Respon untuk perintah teks (dipakai Telegram & WhatsApp).

    Mengenali berbagai bentuk:
      /laporanharian, /laporan_harian, laporanharian, Laporan Harian,
      1.laporan harian (label menu bernomor), 1 (angka menu fallback).
    """
    t = (text or "").strip().lstrip("/!").lower()

    # angka menu murni (fallback saat tombol WhatsApp tidak tampil): "1" -> harian
    if t in NUM_COMMANDS:
        t = NUM_COMMANDS[t]

    # buang nomor menu di depan teks: "1.laporan harian" -> "laporan harian"
    t = re.sub(r"^\d+\s*[.)\-]?\s*", "", t).strip()

    parts = t.split()
    raw = parts[0].split("@")[0] if parts else ""
    # 1) cocokkan seluruh teks (mis. "laporan harian" -> laporanharian)
    cmd = COMMANDS.get(t) or _NORM_COMMANDS.get(re.sub(r"[_\-\s]+", "", t))
    # 2) fallback: kata pertama (mis. "/laporan_harian 7 hari")
    if cmd is None:
        cmd = COMMANDS.get(raw) or _NORM_COMMANDS.get(re.sub(r"[_\-\s]+", "", raw))
    if cmd is None:
        return (
            "❓ Perintah tidak dikenal. Kirim *foto struk* untuk mencatat penjualan,\n"
            "atau /bantuan untuk daftar perintah."
        )
    if cmd == "bantuan":
        return HELP_TEXT
    if cmd == "total":
        return analytics.report_total()
    if cmd == "laporan_harian":
        return analytics.report_daily()
    if cmd == "laporan_mingguan":
        return analytics.report_weekly()
    if cmd == "laporan_bulanan":
        return analytics.report_monthly()
    if cmd == "produk_terlaris":
        return analytics.report_top_products()
    if cmd == "export":
        # Bridge WhatsApp hanya bisa kirim teks; arahkan ke dashboard untuk unduhan
        return (
            "📥 *Ekspor Excel*\n\n"
            "Di WhatsApp file tidak bisa dikirim langsung. "
            "Unduh di dashboard: `http://localhost:8000/dashboard` → tombol *Download Excel*.\n\n"
            "Di Telegram, gunakan /export dan file .xlsx akan dikirim ke chat."
        )
    return HELP_TEXT
