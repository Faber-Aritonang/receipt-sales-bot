"""Unit test pipeline perintah bersama (app/process.py)."""
from app import process


def test_perintah_tanpa_garis_bawah():
    r = process.command_reply("/laporanharian")
    assert r.startswith("📆")
    assert "LAPORAN HARIAN" in r


def test_perintah_dengan_garis_bawah():
    assert process.command_reply("/laporan_harian").startswith("📆")


def test_perintah_dengan_botname():
    r = process.command_reply("/laporanharian@BotFather")
    assert r.startswith("📆")


def test_perintah_huruf_besar():
    assert process.command_reply("/LAPORANMINGGUAN").startswith("🗓️")


def test_perintah_label_menu_whatsapp():
    # user membalas dengan label menu bernomor (mis. "1.laporan harian")
    assert process.command_reply("1.laporan harian").startswith("📆")
    assert process.command_reply("1. laporan harian").startswith("📆")


def test_perintah_bahasa_alami():
    # tanpa garis miring, tanpa garis bawah, huruf kapital acak
    assert process.command_reply("laporan harian").startswith("📆")
    assert process.command_reply("Laporan Harian").startswith("📆")
    assert process.command_reply("laporan mingguan").startswith("🗓️")


def test_perintah_angka_menu():
    # fallback angka murni (tombol WhatsApp tidak tampil)
    assert process.command_reply("1").startswith("📆")
    assert process.command_reply("2").startswith("🗓️")
    assert process.command_reply("7").startswith("🤖")


def test_perintah_tidak_dikenal():
    r = process.command_reply("/laporanharianxx")
    assert r.startswith("❓")


def test_input_kosong_dan_aneh():
    for cmd in ["", "   ", "/", "//"]:
        r = process.command_reply(cmd)
        assert r  # tidak boleh error / crash


def test_bantuan():
    r = process.command_reply("/bantuan")
    assert "SALES CANVAS BOT" in r
    assert "/laporanharian" in r


def test_export_di_whatsapp():
    r = process.command_reply("/export")
    assert "Ekspor Excel" in r
