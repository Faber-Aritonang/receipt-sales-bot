"""Unit test proteksi dashboard: halaman login + password."""
import app.config as config
from fastapi.testclient import TestClient

from app.web.server import create_app


def _make_client(password: str, username: str = "kozoadmin") -> TestClient:
    config.DASHBOARD_PASSWORD = password
    config.DASHBOARD_USERNAME = username
    return TestClient(create_app())


def test_tanpa_password_semua_terbuka(tmp_env):
    c = _make_client("")
    assert c.get("/dashboard").status_code == 200
    assert c.get("/api/analytics/summary").status_code == 200


def test_dashboard_redirect_ke_login_saat_belum_login(tmp_env):
    c = _make_client("rahasia123")
    r = c.get("/dashboard", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/login")


def test_api_ditolak_tanpa_cookie(tmp_env):
    c = _make_client("rahasia123")
    assert c.get("/api/analytics/summary").status_code == 401
    assert c.get("/api/export/xlsx").status_code == 401


def test_halaman_login_tampil(tmp_env):
    c = _make_client("rahasia123")
    r = c.get("/login")
    assert r.status_code == 200
    assert 'type="password"' in r.text
    assert 'type="text"' in r.text  # field username ada


def test_login_password_salah(tmp_env):
    c = _make_client("rahasia123")
    r = c.post("/login", data={"username": "kozoadmin", "password": "salah"})
    assert "Username atau password salah" in r.text
    assert "sales_session" not in str(r.headers.get("set-cookie"))


def test_login_username_salah(tmp_env):
    c = _make_client("rahasia123")
    r = c.post("/login", data={"username": "orang-lain", "password": "rahasia123"})
    assert "Username atau password salah" in r.text
    assert "sales_session" not in str(r.headers.get("set-cookie"))


def test_login_benar_dan_akses_dashboard(tmp_env):
    c = _make_client("rahasia123")
    r = c.post(
        "/login", data={"username": "kozoadmin", "password": "rahasia123"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "sales_session=" in str(r.headers.get("set-cookie"))
    token = r.cookies.get("sales_session")
    assert token

    c.cookies.set("sales_session", token)
    assert c.get("/dashboard").status_code == 200
    assert c.get("/api/analytics/summary").status_code == 200


def test_login_username_kustom(tmp_env):
    c = _make_client("rahasia123", username="bos")
    r = c.post(
        "/login", data={"username": "bos", "password": "rahasia123"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "sales_session=" in str(r.headers.get("set-cookie"))


def test_logout_menutup_akses(tmp_env):
    c = _make_client("rahasia123")
    r = c.post(
        "/login", data={"username": "kozoadmin", "password": "rahasia123"},
        follow_redirects=False,
    )
    token = r.cookies.get("sales_session")
    c.cookies.set("sales_session", token)

    c.get("/logout")
    r = c.get("/dashboard", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/login")


def test_health_dan_webhook_tetap_publik(tmp_env):
    c = _make_client("rahasia123")
    assert c.get("/api/health").status_code == 200
    r = c.post(
        "/api/whatsapp/inbound",
        data={"sender": "x", "type": "text", "text": "halo"},
    )
    # 422 = webhook terpanggil tapi secret salah/kurang -> TIDAK 401 auth guard
    assert r.status_code == 422
