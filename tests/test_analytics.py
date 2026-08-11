"""Unit test analytics (app/analytics.py) dengan data contoh di DB sementara."""
from app import analytics


def test_summary(seed_data):
    s = analytics.summary()
    assert s["total_receipts"] == 2
    assert s["total_revenue"] == 70000.0
    assert s["today_count"] == 1
    assert s["today_revenue"] == 50000.0


def test_summary_db_kosong(tmp_env):
    s = analytics.summary()
    assert s["total_receipts"] == 0
    assert s["total_revenue"] == 0.0
    assert s["today_count"] == 0


def test_daily_series(seed_data):
    d = analytics.daily_series(days=7)
    assert len(d["dates"]) == 7
    assert len(d["revenue"]) == 7
    assert sum(d["count"]) == 1  # hanya 1 struk dalam 7 hari terakhir


def test_top_products(seed_data):
    top = analytics.top_products(10)
    assert top
    assert top[0]["name"] == "Kopi Tubruk"  # 50000 > 20000
    assert top[0]["qty"] == 3
    assert top[0]["revenue"] == 50000.0


def test_payment_breakdown(seed_data):
    p = analytics.payment_breakdown()
    methods = {x["method"]: x for x in p}
    assert methods["QRIS"]["revenue"] == 50000.0
    assert methods["Tunai"]["revenue"] == 20000.0


def test_hourly_series(seed_data):
    h = analytics.hourly_series()
    by_hour = {x["hour"]: x for x in h}
    assert by_hour[9]["revenue"] == 50000.0
    assert by_hour[14]["revenue"] == 20000.0


def test_hourly_series_filter_hari_ini(seed_data):
    # filter per hari: hanya struk tanggal efektif hari ini yang dihitung
    from app import database as db

    h = analytics.hourly_series(day=db.today_iso())
    by_hour = {x["hour"]: x for x in h}
    assert by_hour[9]["revenue"] == 50000.0  # struk hari ini jam 09:15
    assert by_hour[14]["revenue"] == 0.0  # struk 2020-01-05 tidak ikut


def test_summary_struk_tanpa_tanggal(tmp_env):
    """Struk tanpa tanggal (OCR gagal baca) dianggap sebagai penjualan hari ini."""
    from app import database as db

    db.insert_receipt(
        {
            "source": "whatsapp",
            "sender_id": "w9",
            "merchant": "Toko Tanpa Tanggal",
            "receipt_date": None,  # tanggal tidak terbaca OCR
            "receipt_time": "10:00",
            "total": 25000,
            "payment_method": "QRIS",
            "ocr_confidence": "rendah",
        },
        [],
    )
    s = analytics.summary()
    assert s["total_receipts"] == 1
    assert s["today_count"] == 1
    assert s["today_revenue"] == 25000.0


def test_report_daily_tanpa_tanggal(tmp_env):
    """Laporan harian menampilkan struk tanpa tanggal (tidak lagi '0 struk')."""
    from app import database as db

    db.insert_receipt(
        {
            "source": "whatsapp",
            "sender_id": "w9",
            "receipt_date": None,
            "receipt_time": "10:00",
            "total": 25000,
        },
        [],
    )
    r = analytics.report_daily()
    assert "Total hari ini: 1 struk" in r
    assert "Rp 25.000" in r


def test_report_total(seed_data):
    r = analytics.report_total()
    assert "RINGKASAN TOTAL" in r
    assert "Rp 70.000" in r


def test_report_daily(seed_data):
    r = analytics.report_daily()
    assert "LAPORAN HARIAN" in r
    assert "Rp 50.000" in r


def test_report_weekly(seed_data):
    r = analytics.report_weekly()
    assert "7 HARI TERAKHIR" in r


def test_report_monthly(seed_data):
    r = analytics.report_monthly()
    assert "LAPORAN BULAN INI" in r


def test_report_top_products(seed_data):
    r = analytics.report_top_products()
    assert "PRODUK TERLARIS" in r
    assert "Kopi Tubruk" in r
