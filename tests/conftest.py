"""Fixture bersama untuk seluruh test.

Setiap test memakai database & folder upload sementara (tmp_path) sehingga
data asli di `data/` tidak pernah tersentuh.
"""
import os
import sys
from pathlib import Path

import pytest

# pastikan root project ada di sys.path (agar `import app.*` berhasil)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402


@pytest.fixture()
def tmp_env(tmp_path, monkeypatch):
    """Arahkan config ke direktori sementara & siapkan skema DB kosong."""
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))

    from app import database as db

    db.init_db()
    return tmp_path


@pytest.fixture()
def seed_data(tmp_env):
    """Isi DB sementara dengan 2 struk contoh (hari ini & beberapa hari lalu)."""
    from app import database as db

    today = db.today_iso()
    r1 = db.insert_receipt(
        {
            "source": "telegram",
            "sender_id": "t1",
            "merchant": "Toko Kopi Nusantara",
            "receipt_date": today,
            "receipt_time": "09:15",
            "subtotal": 45000,
            "tax": 5000,
            "total": 50000,
            "payment_method": "QRIS",
            "ocr_confidence": "tinggi",
        },
        [
            {"name": "Kopi Tubruk", "qty": 2, "unit_price": 15000, "total_price": 30000},
            {"name": "Roti Bakar", "qty": 1, "unit_price": 15000, "total_price": 15000},
        ],
    )
    r2 = db.insert_receipt(
        {
            "source": "whatsapp",
            "sender_id": "w1",
            "merchant": "Toko Kopi Nusantara",
            "receipt_date": "2020-01-05",
            "receipt_time": "14:30",
            "subtotal": 20000,
            "tax": 0,
            "total": 20000,
            "payment_method": "Tunai",
            "ocr_confidence": "sedang",
        },
        [
            {"name": "Kopi Tubruk", "qty": 1, "unit_price": 20000, "total_price": 20000},
        ],
    )
    return {"today": today, "receipt_ids": [r1, r2]}


@pytest.fixture()
def api_client(tmp_env):
    """TestClient FastAPI dengan proteksi nonaktif (password kosong)."""
    config.DASHBOARD_PASSWORD = ""
    from fastapi.testclient import TestClient

    from app.web.server import create_app

    return TestClient(create_app())
