"""Bot Telegram — menerima foto struk & melayani perintah laporan."""
from __future__ import annotations

import asyncio
import io
import logging

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from .. import config, export, process, whitelist

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
        [KeyboardButton("/whitelist 📋"), KeyboardButton("/izinkan ➕"), KeyboardButton("/blokir ➖")],
        [KeyboardButton("/bantuan ❓")],
    ]
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Ketuk tombol atau ketik perintah…",
    )


def _clear_pending_whitelist(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Bersihkan alur menunggu nomor whitelist (mis. user membatalkan)."""
    context.user_data.pop("pending_whitelist", None)


async def _start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Anda tidak punya akses ke bot ini.")
        return
    _clear_pending_whitelist(context)
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
    _clear_pending_whitelist(context)
    await update.message.reply_text(
        process.HELP_TEXT, parse_mode="Markdown", reply_markup=_menu_markup()
    )


async def _command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_user.id):
        return
    _clear_pending_whitelist(context)
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
    _clear_pending_whitelist(context)

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


def _wa_whitelist_text(result: dict) -> str:
    """Format respons whitelist jadi teks yang rapi."""
    if not result.get("ok"):
        return f"⚠️ Gagal: {result.get('error', 'tidak diketahui')}"
    allowed = result.get("allowed") or []
    if not allowed:
        return "🌍 Mode terbuka — SEMUA nomor WhatsApp boleh memakai bot."
    lines = ["🔒 *Nomor WhatsApp yang diizinkan:*"]
    lines += [f"{i}. {n}" for i, n in enumerate(allowed, 1)]
    lines.append("")
    lines.append("Untuk menambah: /izinkan 628xxxx / menghapus: /blokir 628xxxx")
    return "\n".join(lines)


async def _whitelist_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/izinkan [628xxxx] — tambah nomor WhatsApp ke daftar yang boleh memakai bot.

    Tanpa nomor -> bot meminta nomor di pesan berikutnya (alur tombol).
    """
    if not _allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Anda tidak punya akses ke bot ini.")
        return
    if not context.args:
        context.user_data["pending_whitelist"] = "add"
        await update.message.reply_text(
            "➕ Ketik nomor WhatsApp yang mau diizinkan (format internasional tanpa +, "
            "contoh: 628123456789)."
        )
        return
    number = context.args[0]
    result = whitelist.wa_whitelist_add(number)
    await update.message.reply_text(_wa_whitelist_text(result), parse_mode="Markdown")


async def _whitelist_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/blokir [628xxxx] — hapus nomor dari daftar yang diizinkan.

    Tanpa nomor -> bot meminta nomor di pesan berikutnya (alur tombol).
    """
    if not _allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Anda tidak punya akses ke bot ini.")
        return
    if not context.args:
        context.user_data["pending_whitelist"] = "remove"
        await update.message.reply_text(
            "➖ Ketik nomor WhatsApp yang mau diblokir (format internasional tanpa +, "
            "contoh: 628123456789)."
        )
        return
    number = context.args[0]
    result = whitelist.wa_whitelist_remove(number)
    await update.message.reply_text(_wa_whitelist_text(result), parse_mode="Markdown")


async def _whitelist_pending_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Teks biasa saat menunggu nomor dari alur tombol /izinkan atau /blokir."""
    action = context.user_data.pop("pending_whitelist", None)
    if not action:
        return  # bukan bagian alur whitelist — abaikan seperti sebelumnya
    number = (update.message.text or "").strip()
    if action == "add":
        result = whitelist.wa_whitelist_add(number)
    else:
        result = whitelist.wa_whitelist_remove(number)
    await update.message.reply_text(_wa_whitelist_text(result), parse_mode="Markdown")


async def _whitelist_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/whitelist — tampilkan daftar nomor WhatsApp yang diizinkan.
    """
    if not _allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Anda tidak punya akses ke bot ini.")
        return
    _clear_pending_whitelist(context)
    result = whitelist.wa_whitelist_list()
    await update.message.reply_text(_wa_whitelist_text(result), parse_mode="Markdown")


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
    # kelola whitelist nomor WhatsApp
    app.add_handler(CommandHandler(["izinkan", "tambah"], _whitelist_add))
    app.add_handler(CommandHandler(["blokir", "hapus"], _whitelist_remove))
    app.add_handler(CommandHandler(["whitelist", "daftar"], _whitelist_list))
    # teks biasa: dipakai untuk nomor yang dikirim setelah tombol /izinkan /blokir
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _whitelist_pending_text)
    )
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
