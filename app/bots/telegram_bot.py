"""Bot Telegram — menerima foto struk & melayani perintah laporan."""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import time

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from .. import config, export, process, whitelist

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Akses: ID Telegram (TELEGRAM_ALLOWED_IDS) ATAU nomor telepon yang terdaftar
# di whitelist (daftar nomor yang SAMA dengan bot WhatsApp). Telegram tidak
# memberi tahu nomor pengguna kecuali ia membagikannya lewat tombol "Bagikan
# Nomor", jadi pengguna baru diminta membagikan nomor sekali; setelah cocok
# dengan whitelist, user id-nya diingat (persisten) dan lolos di pesan berikut.
# ---------------------------------------------------------------------------

# user_id (str) -> nomor telepon terverifikasi; disimpan ke data/ agar tidak
# perlu membagikan nomor lagi setelah bot di-restart.
_verified: dict[str, str] = {}
_VERIFIED_FILE = "telegram_verified.json"

# Cache daftar whitelist dari bridge (60 dtk) agar tidak memanggil HTTP tiap pesan.
_whitelist_cache: set[str] | None = None
_whitelist_cache_at: float = 0.0
_WHITELIST_CACHE_TTL = 60.0


def _verified_file() -> str:
    return os.path.join(config.DATA_DIR, _VERIFIED_FILE)


def _load_verified() -> None:
    """Muat daftar user yang pernah terverifikasi dari disk (persisten)."""
    global _verified
    try:
        with open(_verified_file(), encoding="utf-8") as fh:
            data = json.load(fh)
        _verified = {str(k): str(v) for k, v in data.items()}
    except FileNotFoundError:
        _verified = {}
    except Exception as exc:  # pragma: no cover - file rusak
        log.warning("gagal memuat daftar user terverifikasi: %s", exc)
        _verified = {}


def _save_verified(user_id: int, phone: str) -> None:
    """Simpan user yang nomornya cocok dengan whitelist (persisten)."""
    _verified[str(user_id)] = phone
    try:
        with open(_verified_file(), "w", encoding="utf-8") as fh:
            json.dump(_verified, fh, indent=2)
    except Exception as exc:  # pragma: no cover
        log.warning("gagal menyimpan daftar user terverifikasi: %s", exc)


def _normalize_phone(raw: str | None) -> str:
    """Bersihkan nomor ke format internasional tanpa '+' (628...).

    "+62 812-3456-789" -> "628123456789"; "08123456789" -> "628123456789"
    (angka 0 di depan nomor lokal Indonesia dianggap kode negara 62).
    """
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    return digits


def _whitelist_numbers() -> set[str] | None:
    """Daftar nomor yang diizinkan saat ini (cache singkat 60 dtk).

    None = status whitelist tidak diketahui (gagal ambil & belum pernah
    berhasil) — pemanggil harus memperlakukan sebagai tertutup (fail closed)
    agar bot tidak terbuka untuk semua orang saat bridge mati.
    """
    global _whitelist_cache, _whitelist_cache_at
    now = time.monotonic()
    if _whitelist_cache is not None and now - _whitelist_cache_at < _WHITELIST_CACHE_TTL:
        return _whitelist_cache
    result = whitelist.wa_whitelist_list()
    if result.get("ok"):
        _whitelist_cache = set(result.get("allowed") or [])
        _whitelist_cache_at = now
        return _whitelist_cache
    return _whitelist_cache  # None bila belum pernah berhasil ambil


def _invalidate_whitelist_cache() -> None:
    """Paksa ambil ulang setelah /izinkan atau /blokir berhasil."""
    global _whitelist_cache
    _whitelist_cache = None


def _allowed(user_id: int | None) -> bool:
    """Apakah pengguna Telegram boleh memakai bot.

    Sumber izin (cukup salah satu):
      1. ID Telegram ada di TELEGRAM_ALLOWED_IDS.
      2. Whitelist nomor kosong (mode terbuka) dan TELEGRAM_ALLOWED_IDS juga
         kosong -> semua orang boleh (perilaku lama).
      3. Nomor telepon terverifikasi dan MASIH terdaftar di whitelist
         (daftar nomor sama dengan bot WhatsApp; nomor yang dihapus dari
         whitelist otomatis kehilangan akses).
    """
    if user_id and user_id in config.TELEGRAM_ALLOWED_IDS:
        return True
    numbers = _whitelist_numbers()
    if numbers is None:
        return False  # status tidak diketahui -> tutup akses
    if not numbers:
        return not config.TELEGRAM_ALLOWED_IDS
    phone = _verified.get(str(user_id))
    return bool(phone and phone in numbers)


def _contact_request_markup() -> ReplyKeyboardMarkup:
    """Keyboard satu tombol: minta pengguna membagikan nomornya."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Bagikan Nomor", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def _deny_or_request_contact(update: Update) -> None:
    """Balasan untuk pengguna tanpa akses.

    Bila whitelist nomor aktif -> minta bagikan nomor untuk dicocokkan.
    Bila tidak (mis. akses dibatasi hanya lewat TELEGRAM_ALLOWED_IDS) -> tolak.
    """
    if _whitelist_numbers():
        await update.message.reply_text(
            "⛔ Bot ini hanya bisa dipakai oleh nomor yang terdaftar di whitelist.\n"
            "Ketuk tombol di bawah untuk membagikan nomor Anda — bot akan "
            "mencocokkannya dengan daftar izin.",
            reply_markup=_contact_request_markup(),
        )
    else:
        await update.message.reply_text("⛔ Anda tidak punya akses ke bot ini.")


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
        await _deny_or_request_contact(update)
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
        await _deny_or_request_contact(update)
        return
    _clear_pending_whitelist(context)
    await update.message.reply_text(
        process.HELP_TEXT, parse_mode="Markdown", reply_markup=_menu_markup()
    )


async def _command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_user.id):
        await _deny_or_request_contact(update)
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
        await _deny_or_request_contact(update)
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
        return "🌍 Mode terbuka — SEMUA nomor boleh memakai bot (Telegram & WhatsApp)."
    lines = ["🔒 *Nomor yang diizinkan:*"]
    lines += [f"{i}. {n}" for i, n in enumerate(allowed, 1)]
    lines.append("")
    lines.append("Untuk menambah: /izinkan 628xxxx / menghapus: /blokir 628xxxx")
    return "\n".join(lines)


async def _whitelist_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/izinkan [628xxxx] — tambah nomor WhatsApp ke daftar yang boleh memakai bot.

    Tanpa nomor -> bot meminta nomor di pesan berikutnya (alur tombol).
    """
    if not _allowed(update.effective_user.id):
        await _deny_or_request_contact(update)
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
    if result.get("ok"):
        _invalidate_whitelist_cache()
    await update.message.reply_text(_wa_whitelist_text(result), parse_mode="Markdown")


async def _whitelist_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/blokir [628xxxx] — hapus nomor dari daftar yang diizinkan.

    Tanpa nomor -> bot meminta nomor di pesan berikutnya (alur tombol).
    """
    if not _allowed(update.effective_user.id):
        await _deny_or_request_contact(update)
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
    if result.get("ok"):
        _invalidate_whitelist_cache()
    await update.message.reply_text(_wa_whitelist_text(result), parse_mode="Markdown")


async def _whitelist_pending_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Teks biasa saat menunggu nomor dari alur tombol /izinkan atau /blokir."""
    if not _allowed(update.effective_user.id):
        await _deny_or_request_contact(update)
        return
    action = context.user_data.pop("pending_whitelist", None)
    if not action:
        return  # bukan bagian alur whitelist — abaikan seperti sebelumnya
    number = (update.message.text or "").strip()
    if action == "add":
        result = whitelist.wa_whitelist_add(number)
    else:
        result = whitelist.wa_whitelist_remove(number)
    if result.get("ok"):
        _invalidate_whitelist_cache()
    await update.message.reply_text(_wa_whitelist_text(result), parse_mode="Markdown")


async def _contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Terima nomor yang dibagikan pengguna & cocokkan dengan whitelist.

    Nomor yang cocok -> user diingat (persisten) & langsung mendapat akses.
    """
    _clear_pending_whitelist(context)
    contact = update.message.contact
    phone = _normalize_phone(contact.phone_number if contact else "")
    if not phone:
        await update.message.reply_text("⚠️ Nomor tidak terbaca. Coba lagi.")
        return
    numbers = _whitelist_numbers()
    if not numbers:
        # mode terbuka — verifikasi tidak diperlukan
        await update.message.reply_text(
            "✅ Terima kasih! Bot terbuka untuk semua nomor saat ini.\n\n"
            "Kirim *foto struk* penjualan atau ketuk tombol di bawah.\n"
            "Ketik /bantuan untuk daftar laporan.",
            parse_mode="Markdown",
            reply_markup=_menu_markup(),
        )
        return
    if phone in numbers:
        _save_verified(update.effective_user.id, phone)
        await update.message.reply_text(
            "✅ Nomor Anda terdaftar di whitelist — akses dibuka!\n\n"
            "Kirim *foto struk* penjualan atau ketuk tombol di bawah.\n"
            "Ketik /bantuan untuk daftar laporan.",
            parse_mode="Markdown",
            reply_markup=_menu_markup(),
        )
        return
    await _deny_or_request_contact(update)


async def _whitelist_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/whitelist — tampilkan daftar nomor WhatsApp yang diizinkan.
    """
    if not _allowed(update.effective_user.id):
        await _deny_or_request_contact(update)
        return
    _clear_pending_whitelist(context)
    result = whitelist.wa_whitelist_list()
    await update.message.reply_text(_wa_whitelist_text(result), parse_mode="Markdown")


async def _photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_user.id):
        await _deny_or_request_contact(update)
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
    _load_verified()
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler(["start", "mulai"], _start))
    app.add_handler(CommandHandler(["bantuan", "help"], _help))
    app.add_handler(CommandHandler("export", _export))
    # kelola whitelist nomor WhatsApp
    app.add_handler(CommandHandler(["izinkan", "tambah"], _whitelist_add))
    app.add_handler(CommandHandler(["blokir", "hapus"], _whitelist_remove))
    app.add_handler(CommandHandler(["whitelist", "daftar"], _whitelist_list))
    # nomor yang dibagikan pengguna untuk verifikasi akses (whitelist)
    app.add_handler(MessageHandler(filters.CONTACT, _contact))
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
