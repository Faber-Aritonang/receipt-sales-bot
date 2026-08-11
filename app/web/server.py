"""Server FastAPI: API analytics + halaman dashboard + webhook WhatsApp."""
from __future__ import annotations

import logging
import secrets
import time
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from .. import analytics, backup, config, database as db, export
from ..bots.whatsapp_api import router as whatsapp_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

_DASHBOARD = Path(__file__).parent / "dashboard.html"

# ---- Proteksi dashboard (halaman login + password) ----
# Sesi disimpan in-memory: {token: waktu_kadaluarsa}. Cookie httpOnly, 7 hari.
_SESSION_COOKIE = "sales_session"
_SESSION_TTL = 7 * 24 * 3600
_sessions: dict[str, float] = {}

# Path yang selalu publik (tanpa login)
# ("qr" ikut publik: hanya redirect ke bridge; halaman QR-nya sendiri sudah
# dilindungi QR_PASSWORD di bridge)
_PUBLIC_PREFIXES = ("/api/health", "/api/whatsapp", "/login", "/logout", "/qr")


def _is_public(path: str) -> bool:
    return any(path == p or path.startswith(p) for p in _PUBLIC_PREFIXES)


def _protected() -> bool:
    """True jika password dashboard di-set (proteksi aktif)."""
    return bool(config.DASHBOARD_PASSWORD)


def _bridge_url(request: Request) -> str:
    """URL dasar bridge WhatsApp: host request + BRIDGE_PORT (fallback BRIDGE_URL)."""
    host = request.headers.get("host", "")
    hostname = host.split(":")[0] if host else ""
    return f"http://{hostname}:{config.BRIDGE_PORT}" if hostname else config.BRIDGE_URL


def _session_valid(token: str | None) -> bool:
    if not token:
        return False
    exp = _sessions.get(token)
    if exp is None:
        return False
    if time.time() > exp:
        _sessions.pop(token, None)
        return False
    return True


_LOGIN_HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Masuk — Sales Canvas</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
    min-height: 100vh; display: grid; place-items: center; padding: 24px;
    background: radial-gradient(1000px 500px at 80% -10%, rgba(108,140,255,.18), transparent 60%),
                radial-gradient(800px 400px at 0% 100%, rgba(34,211,165,.10), transparent 55%),
                #0b1020;
    color: #e8ecf8;
  }
  .card {
    width: min(380px, 100%); background: linear-gradient(180deg, #141b33, #1a2342);
    border: 1px solid #263055; border-radius: 18px; padding: 34px 30px;
    box-shadow: 0 24px 60px rgba(0,0,0,.5);
  }
  .logo {
    width: 52px; height: 52px; border-radius: 14px; margin: 0 auto 16px;
    background: linear-gradient(135deg, #6c8cff, #22d3a5); display: grid; place-items: center;
    font-size: 26px; box-shadow: 0 8px 24px rgba(108,140,255,.35);
  }
  h1 { font-size: 19px; text-align: center; margin-bottom: 4px; }
  p.sub { color: #93a0c4; font-size: 13px; text-align: center; margin-bottom: 24px; }
  label { display: block; font-size: 12px; color: #93a0c4; text-transform: uppercase; letter-spacing: .06em; margin-bottom: 6px; }
  input[type=password] {
    width: 100%; padding: 12px 14px; border-radius: 10px; border: 1px solid #263055;
    background: #0b1020; color: #e8ecf8; font-size: 14px; outline: none;
    transition: border-color .15s;
  }
  input[type=password]:focus { border-color: #6c8cff; }
  button {
    width: 100%; margin-top: 18px; padding: 12px; border: 0; border-radius: 10px;
    background: linear-gradient(135deg, #6c8cff, #22d3a5); color: #0b1020;
    font-size: 14px; font-weight: 700; cursor: pointer; transition: transform .15s, opacity .15s;
  }
  button:hover { transform: translateY(-1px); opacity: .92; }
  .err {
    margin-top: 14px; padding: 10px 12px; border-radius: 8px; font-size: 13px;
    background: rgba(248,113,113,.12); border: 1px solid rgba(248,113,113,.4); color: #f87171;
  }
</style>
</head>
<body>
  <form class="card" method="post" action="/login">
    <div class="logo">🧾</div>
    <h1>Sales Canvas</h1>
    <p class="sub">Masukkan password untuk membuka dashboard analisa penjualan</p>
    <label for="password">Password</label>
    <input type="password" id="password" name="password" placeholder="••••••••" autofocus required />
    {error_html}
    <button type="submit">🔓 Masuk</button>
  </form>
</body>
</html>
"""


def _login_page(error: bool = False) -> HTMLResponse:
    err = '<div class="err">⛔ Password salah. Coba lagi.</div>' if error else ""
    return HTMLResponse(_LOGIN_HTML.replace("{error_html}", err))


def create_app() -> FastAPI:
    db.init_db()
    # backup otomatis saat server start (hanya jika belum ada backup hari ini)
    try:
        backup.run_backup()
    except Exception:
        log.exception("gagal menjalankan backup saat start")
    app = FastAPI(title="Sales Canvas API", version="1.0.0")
    app.include_router(whatsapp_router)

    @app.get("/", include_in_schema=False)
    async def index():
        # proteksi ditangani auth_guard (middleware)
        return FileResponse(_DASHBOARD)

    @app.get("/dashboard", include_in_schema=False)
    async def dashboard():
        # proteksi ditangani auth_guard (middleware)
        return FileResponse(_DASHBOARD)

    @app.get("/login", include_in_schema=False)
    async def login_page():
        if not _protected():
            return RedirectResponse("/dashboard", status_code=302)
        return _login_page()

    @app.post("/login", include_in_schema=False)
    async def login_submit(password: str = Form(...)):
        if not _protected():
            return RedirectResponse("/dashboard", status_code=302)
        if not secrets.compare_digest(password, config.DASHBOARD_PASSWORD):
            # jeda kecil untuk memperlambat brute-force
            time.sleep(0.5)
            return _login_page(error=True)
        token = secrets.token_urlsafe(32)
        _sessions[token] = time.time() + _SESSION_TTL
        resp = RedirectResponse("/dashboard", status_code=302)
        resp.set_cookie(
            _SESSION_COOKIE,
            token,
            max_age=_SESSION_TTL,
            httponly=True,
            samesite="lax",
        )
        # cegah halaman dashboard tersimpan di cache browser setelah logout
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/logout", include_in_schema=False)
    async def logout(request: Request):
        token = request.cookies.get(_SESSION_COOKIE)
        if token:
            _sessions.pop(token, None)
        resp = RedirectResponse("/login", status_code=302)
        resp.delete_cookie(_SESSION_COOKIE)
        return resp

    @app.get("/qr", include_in_schema=False)
    async def qr_redirect(request: Request):
        """Arahkan /qr (yang sering salah dibuka di port API 8000) ke bridge.

        Memakai host yang sama dengan request agar bekerja dari localhost maupun
        VPS; fallback ke config.BRIDGE_URL bila host tidak tersedia.
        """
        return RedirectResponse(f"{_bridge_url(request)}/qr", status_code=302)

    @app.get("/qr.png", include_in_schema=False)
    async def qr_png_redirect(request: Request):
        """Gambar QR mentah juga ada di bridge — arahkan ke sana."""
        return RedirectResponse(f"{_bridge_url(request)}/qr.png", status_code=302)

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/export/xlsx")
    async def api_export_xlsx():
        """Unduh seluruh data penjualan sebagai file Excel (.xlsx)."""
        data = export.build_xlsx()
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{export.export_filename()}"'
            },
        )

    @app.get("/api/analytics/summary")
    async def api_summary():
        return analytics.summary()

    @app.get("/api/analytics/daily")
    async def api_daily(days: int = 30):
        return analytics.daily_series(min(max(days, 1), 90))

    @app.get("/api/analytics/products")
    async def api_products(limit: int = 10):
        return analytics.top_products(min(max(limit, 1), 50))

    @app.get("/api/analytics/payments")
    async def api_payments():
        return analytics.payment_breakdown()

    @app.get("/api/analytics/hourly")
    async def api_hourly():
        return analytics.hourly_series()

    @app.get("/api/receipts")
    async def api_receipts(limit: int = 20):
        return analytics.recent(min(max(limit, 1), 100))

    @app.middleware("http")
    async def auth_guard(request: Request, call_next):
        """Proteksi semua halaman & API kecuali path publik."""
        path = request.url.path
        if not _protected() or _is_public(path):
            return await call_next(request)
        if _session_valid(request.cookies.get(_SESSION_COOKIE)):
            return await call_next(request)
        # API -> 401 JSON; halaman -> redirect ke login
        if path.startswith("/api/"):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return RedirectResponse("/login", status_code=302)

    @app.exception_handler(Exception)
    async def _unhandled(request, exc):
        log.exception("unhandled error pada %s", request.url.path)
        return JSONResponse({"error": "internal error"}, status_code=500)

    return app
