"""Bot Telegram — menerima foto struk & melayani perintah laporan."""
from __future__ import annotations

import asyncio
import io
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from .. import config, process

log = logging.getLogger(__name__)


def _allowed(user_id: int | None) -> bool:
    if not config.TELEGRAM_ALLOWED_IDS:
        return True
    return user_id in config.TELEGRAM_ALLOWED_IDS


async def _start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Anda tidak punya akses ke bot ini.")
        return
    await update.message.reply_text(
        "🤖 *Selamat datang di Sales Canvas Bot!*\n\n"
        "Kirim *foto struk* penjualan, nanti otomatis dicatat & dianalisa.\n"
        "Gunakan /bantuan untuk daftar laporan.",
        parse_mode="Markdown",
    )


async def _help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_user.id):
        return
    await update.message.reply_text(process.HELP_TEXT, parse_mode="Markdown")


async def _command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_user.id):
        return
    text = update.message.text or ""
    await update.message.reply_text(process.command_reply(text), parse_mode="Markdown")


async def _photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Anda tidak punya akses ke bot ini.")
        return

    status = await update.message.reply_text("⏳ Membaca struk…")
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        buf = io.BytesIO()
        await file.download_to_memory(buf)

        sender = str(update.effective_user.id)
        # OCR lambat -> jalankan di executor agar polling telegram tidak macet
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, process.handle_image, buf.getvalue(), "telegram", sender
        )
        await status.edit_text(result["reply"], parse_mode="Markdown")
    except Exception as exc:
        log.exception("gagal memproses foto dari %s", update.effective_user.id)
        await status.edit_text(f"⚠️ Terjadi kesalahan saat membaca struk: {exc}")


def build_app(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler(["start", "mulai"], _start))
    app.add_handler(CommandHandler(["bantuan", "help"], _help))
    app.add_handler(
        CommandHandler(
            ["laporan_harian", "laporan_mingguan", "laporan_bulanan", "produk_terlaris", "total", "ringkasan"],
            _command,
        )
    )
    app.add_handler(MessageHandler(filters.PHOTO, _photo))
    return app
