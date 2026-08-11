"""Menjalankan server API/dashboard + bot Telegram bersamaan.

Cara pakai:
    cp .env.example .env   # isi TELEGRAM_BOT_TOKEN
    python run.py

Bot WhatsApp berjalan terpisah (lihat whatsapp-bridge/index.js):
    node whatsapp-bridge/index.js
"""
import asyncio
import logging

import uvicorn

from app import backup, config
from app.web.server import create_app

log = logging.getLogger("run")


async def _backup_loop(interval: float = 24 * 3600) -> None:
    """Backup harian otomatis selagi server menyala (tidak memblokir server)."""
    while True:
        await asyncio.sleep(interval)
        try:
            # to_thread: backup DB sinkron tidak boleh memblokir polling Telegram
            created, removed = await asyncio.to_thread(backup.run_backup)
            log.info("backup harian: %s (dihapus %d file lama)",
                     created or "sudah ada hari ini", len(removed))
        except Exception:
            log.exception("backup harian gagal")


async def main() -> None:
    api = create_app()
    server_cfg = uvicorn.Config(api, host=config.API_HOST, port=config.API_PORT, log_level="info")
    server = uvicorn.Server(server_cfg)

    tg_app = None
    if config.TELEGRAM_BOT_TOKEN:
        from app.bots.telegram_bot import build_app

        tg_app = build_app(config.TELEGRAM_BOT_TOKEN)
    else:
        log.warning("TELEGRAM_BOT_TOKEN kosong — bot Telegram dinonaktifkan (isi .env untuk mengaktifkan).")

    log.info("Dashboard: http://localhost:%s/dashboard", config.API_PORT)

    if tg_app is None:
        await asyncio.gather(server.serve(), _backup_loop())
        return

    async def run_telegram() -> None:
        await tg_app.initialize()
        await tg_app.start()
        await tg_app.updater.start_polling()
        try:
            await asyncio.Event().wait()
        finally:
            await tg_app.updater.stop()
            await tg_app.stop()
            await tg_app.shutdown()

    await asyncio.gather(server.serve(), run_telegram(), _backup_loop())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSelesai. Sampai jumpa!")
