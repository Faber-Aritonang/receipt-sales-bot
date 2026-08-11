"""Bot Telegram — menerima foto struk & melayani perintah laporan."""
from __future__ import annotations

import asyncio
import io
import logging

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from .. import config, export, process

log = logging.getLogger(__name__)


def _allowed(user_id: int | None) -> bool:
    if not config.TELEGRAM_ALLOWED_IDS:
        return True
    return user_id in config.TELEGRAM_ALLOWED_IDS


def _menu_markup() -> ReplyKeyboardMarkup:
    """Keyboard perintah yang menempel di bawah kolom ketik.

    Mengetuk tombol sama dengan mengirim perintah tersebut.
    """
    rows = [
        [KeyboardButton("/laporanharian 📆"), KeyboardButton("/laporanmingguan 🗓️")],
        [KeyboardButton("/laporanbulanan 📅"), KeyboardButton("/produkterlaris 🏆")],
        [KeyboardButton("/total 💼"), KeyboardButton("/export 📥")],
        [KeyboardButton("/bantuan ❓")],
    ]
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Ketuk tombol atau ketik perintah…",
    )


async def _start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Anda tidak punya akses ke bot ini.")
        return
    await update.message.reply_text(
        "🤖 *Selamat datang di Sales Canvas Bot!*\n\n"
        "Kirim *foto struk* penjualan, nanti otomatis dicatat & dianalisa.\n"
        "Gunakan tombol di bawah atau ketik /bantuan untuk daftar laporan.",
        parse_mode="Markdown",
        reply_markup=_menu_markup(),
    )


async def _help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        process.HELP_TEXT, parse_mode="Markdown", reply_markup=_menu_markup()
    )


async def _command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_user.id):
        return
    text = update.message.text or ""
    try:
        reply = process.command_reply(text)
    except Exception as exc:
        log.exception("gagal memproses perintah %s dari %s", text, update.effective_user.id)
        reply = f"⚠️ Terjadi kesalahan saat memproses perintah: {exc}"
    await update.message.reply_text(
        reply, parse_mode="Markdown", reply_markup=_menu_markup()
    )


async def _export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Kirim file Excel (.xlsx) berisi seluruh data penjualan."""
    if not _allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Anda tidak punya akses ke bot ini.")
        return

    status = await update.message.reply_text(
        "⏳ Menyiapkan file Excel…", reply_markup=_menu_markup()
    )
    try:
        # generate Excel cepat tapi jalan di executor agar polling tidak macet
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, export.build_xlsx)
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=io.BytesIO(data),
            filename=export.export_filename(),
        )
        await status.delete()
    except Exception as exc:
        log.exception("gagal membuat file export dari %s", update.effective_user.id)
        await status.edit_text(f"⚠️ Terjadi kesalahan saat membuat file Excel: {exc}")


async def _photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Anda tidak punya akses ke bot ini.")
        return

    status = await update.message.reply_text(
        "⏳ Membaca struk…", reply_markup=_menu_markup()
    )
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
    app.add_handler(CommandHandler("export", _export))
    app.add_handler(
        CommandHandler(
            [
                # dua bentuk dikenali: dengan & tanpa garis bawah
                "laporan_harian", "laporanharian",
                "laporan_mingguan", "laporanmingguan",
                "laporan_bulanan", "laporanbulanan",
                "produk_terlaris", "produkterlaris",
                "total", "ringkasan",
            ],
            _command,
        )
    )
    app.add_handler(MessageHandler(filters.PHOTO, _photo))
    return app
