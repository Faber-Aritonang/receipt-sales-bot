"""Unit test untuk parser struk (app/parser.py)."""
from app.parser import parse_amount, parse_receipt


def test_parse_amount_berbagai_format():
    assert parse_amount("Rp 12.500") == 12500.0
    assert parse_amount("Rp12.500") == 12500.0
    assert parse_amount("15.000,50") == 15000.50
    assert parse_amount("1000") == 1000.0
    assert parse_amount("harga tidak ada") is None


def test_parse_receipt_lengkap():
    raw = """TOKO KOPI NUSANTARA
Jl. Merdeka No. 12
2026-08-11 09:15
------------------------
Kopi Tubruk
2 x 15000
Roti Bakar 1 x 15000
------------------------
SUBTOTAL    45.000
PPN 11%     5.000
TOTAL       Rp 50.000
QRIS
"""
    p = parse_receipt(raw)
    assert p["merchant"] == "TOKO KOPI NUSANTARA"
    assert p["receipt_date"] == "2026-08-11"
    assert p["receipt_time"] == "09:15"
    assert p["subtotal"] == 45000.0
    assert p["total"] == 50000.0
    assert p["payment_method"] == "QRIS"
    assert len(p["items"]) >= 2
    assert p["confidence"] in ("tinggi", "sedang")


def test_parse_receipt_kosong():
    p = parse_receipt("")
    assert p["merchant"] is None
    assert p["total"] is None
    assert p["items"] == []
    assert p["confidence"] == "rendah"


def test_parse_receipt_total_di_baris_berikutnya():
    """Nominal TOTAL sering berada di baris setelah kata TOTAL."""
    raw = """WARUNG MAKAN SEDAP
05/08/26 12:00
Nasi Goreng 15.000
Es Teh 5.000
TOTAL
20.000
TUNAI
"""
    p = parse_receipt(raw)
    assert p["total"] == 20000.0
    assert p["payment_method"] == "Tunai"
