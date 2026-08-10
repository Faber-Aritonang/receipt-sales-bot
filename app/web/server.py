"""Server FastAPI: API analytics + halaman dashboard + webhook WhatsApp."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from .. import analytics, config, database as db
from ..bots.whatsapp_api import router as whatsapp_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

_DASHBOARD = Path(__file__).parent / "dashboard.html"


def create_app() -> FastAPI:
    db.init_db()
    app = FastAPI(title="Sales Canvas API", version="1.0.0")
    app.include_router(whatsapp_router)

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(_DASHBOARD)

    @app.get("/dashboard", include_in_schema=False)
    async def dashboard():
        return FileResponse(_DASHBOARD)

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

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

    @app.exception_handler(Exception)
    async def _unhandled(request, exc):
        log.exception("unhandled error pada %s", request.url.path)
        return JSONResponse({"error": "internal error"}, status_code=500)

    return app
