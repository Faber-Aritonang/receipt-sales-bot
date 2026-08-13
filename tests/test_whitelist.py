"""Unit test modul whitelist (app/whitelist.py) — urllib dimock, tanpa bridge."""
import asyncio
import json
import types
import urllib.request

import pytest

import app.whitelist as whitelist


@pytest.fixture(autouse=True)
def _tg_access_open(tmp_env, monkeypatch):
    """Default test: mode lama (whitelist kosong = semua orang boleh).

    Test alur whitelist/ekspor memakai status terbuka agar cek akses tidak
    memblokir; test khusus akses nomor meng-override _whitelist_numbers()
    (atau memakai monkeypatch.undo() untuk menguji fungsi aslinya).
    """
    from app.bots import telegram_bot as tb

    tb._verified = {}
    tb._whitelist_cache = None
    monkeypatch.setattr(tb, "_whitelist_numbers", lambda: set())


class _FakeResp:
    def __init__(self, data: dict):
        self._data = json.dumps(data).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(payload: dict):
    def urlopen(req, timeout=10):
        captured = req
        whitelist._last_req = captured  # untuk diinspeksi test
        whitelist._last_payload = json.loads(captured.data)
        assert captured.get_method() == "POST"
        return _FakeResp(payload)

    return urlopen


def test_add_mengirim_action_dan_nomor(tmp_env, monkeypatch):
    monkeypatch.setattr(whitelist, "_call", lambda a, n: {"ok": True, "allowed": [n]})
    r = whitelist.wa_whitelist_add("628123456789")
    assert r["ok"] is True
    assert "628123456789" in r["allowed"]


def test_remove_mengirim_action_dan_nomor(tmp_env, monkeypatch):
    captured = {}

    def fake_call(action, number):
        captured["action"] = action
        captured["number"] = number
        return {"ok": True, "allowed": ["6280000000000"]}

    monkeypatch.setattr(whitelist, "_call", fake_call)
    whitelist.wa_whitelist_remove("628123456789")
    assert captured["action"] == "remove"
    assert captured["number"] == "628123456789"


def test_list_payload_ke_bridge(tmp_env, monkeypatch):
    resp = {"ok": True, "allowed": ["6280000000000", "6281111111111"]}
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(resp))
    r = whitelist.wa_whitelist_list()
    assert r["ok"] is True
    assert len(r["allowed"]) == 2
    # payload harus berisi action=list & header secret
    assert whitelist._last_payload["action"] == "list"
    assert whitelist._last_payload.get("number") is None
    headers = {k.lower(): v for k, v in whitelist._last_req.headers.items()}
    assert headers["x-secret"]


def test_bridge_gagal_dikembalikan_tanpa_raise(tmp_env, monkeypatch):
    def boom(req, timeout=10):
        raise OSError("koneksi ditolak")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    r = whitelist.wa_whitelist_list()
    assert r["ok"] is False
    assert "bridge tidak merespons" in r["error"]


# ---------------------------------------------------------------------------
# Alur interaktif tombol Telegram: /izinkan tanpa nomor -> minta nomor ->
# pesan berikutnya diproses. Fungsi diimpor langsung dari telegram_bot.
# ---------------------------------------------------------------------------


def _fake_update(text="", user_id=1):
    """Objek Update/mini dengan .message.reply_text yang mencatat balasan."""
    replies = []

    async def reply_text(*a, **k):
        replies.append((a, k))

    msg = types.SimpleNamespace(text=text, reply_text=reply_text)
    update = types.SimpleNamespace(
        effective_user=types.SimpleNamespace(id=user_id),
        effective_chat=types.SimpleNamespace(id=1),
        message=msg,
    )
    return update, replies


def _run(coro):
    return asyncio.run(coro)


def test_izinkan_tanpa_nomor_minta_input(tmp_env, monkeypatch):
    """Tombol /izinkan (tanpa nomor) -> set pending & minta nomor."""
    from app.bots import telegram_bot as tb

    update, replies = _fake_update("/izinkan")
    context = types.SimpleNamespace(user_data={}, args=[])
    _run(tb._whitelist_add(update, context))
    assert context.user_data.get("pending_whitelist") == "add"
    assert replies and "Ketik nomor" in replies[0][0][0]


def test_blokir_tanpa_nomor_minta_input(tmp_env, monkeypatch):
    """Tombol /blokir (tanpa nomor) -> set pending & minta nomor."""
    from app.bots import telegram_bot as tb

    update, replies = _fake_update("/blokir")
    context = types.SimpleNamespace(user_data={}, args=[])
    _run(tb._whitelist_remove(update, context))
    assert context.user_data.get("pending_whitelist") == "remove"
    assert replies and "Ketik nomor" in replies[0][0][0]


def test_teks_saat_pending_add_diproses_sebagai_nomor(tmp_env, monkeypatch):
    """Setelah /izinkan, teks berikutnya diproses sebagai nomor yang ditambahkan."""
    from app.bots import telegram_bot as tb

    captured = {}

    def fake_add(number):
        captured["number"] = number
        return {"ok": True, "allowed": [number]}

    monkeypatch.setattr(whitelist, "wa_whitelist_add", fake_add)
    update, replies = _fake_update(" 628123456789 ")
    context = types.SimpleNamespace(user_data={"pending_whitelist": "add"})
    _run(tb._whitelist_pending_text(update, context))
    assert captured["number"] == "628123456789"
    assert "pending_whitelist" not in context.user_data  # state dibersihkan
    assert replies and replies[0][1]["parse_mode"] == "Markdown"


def test_teks_tanpa_pending_diabaikan(tmp_env, monkeypatch):
    """Teks biasa tanpa pending whitelist -> tidak membalas apa pun."""
    from app.bots import telegram_bot as tb

    update, replies = _fake_update("halo")
    context = types.SimpleNamespace(user_data={})
    _run(tb._whitelist_pending_text(update, context))
    assert replies == []  # tidak ada balasan


def test_tombol_whitelist_ada_di_menu():
    """Menu Telegram memuat tombol kelola whitelist."""
    from app.bots import telegram_bot as tb

    markup = tb._menu_markup()
    labels = [btn.text for row in markup.keyboard for btn in row]
    assert any(l.startswith("/whitelist") for l in labels)
    assert any(l.startswith("/izinkan") for l in labels)
    assert any(l.startswith("/blokir") for l in labels)


def test_whitelist_list_tidak_memicu_export(tmp_env, monkeypatch):
    """Regresi: /whitelist hanya menampilkan daftar — TIDAK mengekspor Excel."""
    from app.bots import telegram_bot as tb
    import app.export as export_mod

    called = []
    monkeypatch.setattr(export_mod, "build_xlsx", lambda: called.append(1) or b"x")
    monkeypatch.setattr(whitelist, "wa_whitelist_list", lambda: {"ok": True, "allowed": ["6281111111111"]})

    update, replies = _fake_update("/whitelist")
    context = types.SimpleNamespace(
        user_data={},
        bot=types.SimpleNamespace(),
        effective_chat=types.SimpleNamespace(id=1),
    )
    _run(tb._whitelist_list(update, context))
    assert called == []  # export tidak boleh dipanggil
    assert replies and "6281111111111" in replies[0][0][0]


def test_export_memanggil_build_xlsx(tmp_env, monkeypatch):
    """Regresi: /export benar-benar membuat & mengirim file Excel."""
    from app.bots import telegram_bot as tb
    import app.export as export_mod

    sent = {}

    async def fake_send_document(**k):
        sent["doc"] = k

    monkeypatch.setattr(export_mod, "build_xlsx", lambda: b"FAKE-XLSX")
    monkeypatch.setattr(export_mod, "export_filename", lambda: "penjualan.xlsx")

    update, replies = _fake_update("/export")
    status = types.SimpleNamespace()

    async def fake_delete():
        pass

    async def fake_edit_text(*a, **k):
        pass

    status.delete = fake_delete
    status.edit_text = fake_edit_text

    # reply_text kedua (status) harus mengembalikan objek dgn delete()
    orig_reply = update.message.reply_text

    async def reply_text(*a, **k):
        await orig_reply(*a, **k)
        return status

    update.message.reply_text = reply_text
    context = types.SimpleNamespace(
        user_data={},
        bot=types.SimpleNamespace(send_document=fake_send_document),
        effective_chat=types.SimpleNamespace(id=1),
    )
    _run(tb._export(update, context))
    doc = sent.get("doc", {}).get("document")
    assert doc is not None
    assert doc.read() == b"FAKE-XLSX"  # BytesIO berisi hasil build_xlsx
    assert sent["doc"]["filename"] == "penjualan.xlsx"


# ---------------------------------------------------------------------------
# Akses Telegram via nomor whitelist (daftar yang sama dengan bot WhatsApp)
# ---------------------------------------------------------------------------


def _contact_update(phone_number, user_id=7):
    """Update mini dengan pesan contact (bukan teks)."""
    replies = []

    async def reply_text(*a, **k):
        replies.append((a, k))

    contact = types.SimpleNamespace(phone_number=phone_number)
    update = types.SimpleNamespace(
        effective_user=types.SimpleNamespace(id=user_id),
        effective_chat=types.SimpleNamespace(id=1),
        message=types.SimpleNamespace(contact=contact, reply_text=reply_text),
    )
    return update, replies


def test_normalize_phone():
    """Nomor dari Telegram dinormalisasi ke format internasional (628...)."""
    from app.bots import telegram_bot as tb

    assert tb._normalize_phone("+62 812-3456-789") == "628123456789"
    assert tb._normalize_phone("08123456789") == "628123456789"
    assert tb._normalize_phone("628123456789") == "628123456789"
    assert tb._normalize_phone("") == ""
    assert tb._normalize_phone(None) == ""


def test_allowed_id_telegram_tetap_lolos(tmp_env, monkeypatch):
    """TELEGRAM_ALLOWED_IDS tetap jadi izin utama walau whitelist aktif."""
    from app import config
    from app.bots import telegram_bot as tb

    monkeypatch.setattr(config, "TELEGRAM_ALLOWED_IDS", {42})
    monkeypatch.setattr(tb, "_whitelist_numbers", lambda: {"628123456789"})
    assert tb._allowed(42) is True
    assert tb._allowed(43) is False


def test_allowed_nomor_terverifikasi_di_whitelist(tmp_env, monkeypatch):
    """Nomor terverifikasi yang masih ada di whitelist -> diizinkan."""
    from app.bots import telegram_bot as tb

    monkeypatch.setattr(tb, "_whitelist_numbers", lambda: {"628123456789"})
    tb._verified = {"7": "628123456789"}
    assert tb._allowed(7) is True
    assert tb._allowed(8) is False


def test_allowed_nomor_dihapus_dari_whitelist_hilang_akses(tmp_env, monkeypatch):
    """Nomor yang diblokir otomatis kehilangan akses (tanpa verifikasi ulang)."""
    from app.bots import telegram_bot as tb

    monkeypatch.setattr(tb, "_whitelist_numbers", lambda: {"6280000000000"})
    tb._verified = {"7": "628123456789"}
    assert tb._allowed(7) is False


def test_allowed_whitelist_kosong_mode_terbuka(tmp_env, monkeypatch):
    """Whitelist kosong + TELEGRAM_ALLOWED_IDS kosong -> semua orang boleh."""
    from app.bots import telegram_bot as tb

    monkeypatch.setattr(tb, "_whitelist_numbers", lambda: set())
    assert tb._allowed(7) is True


def test_allowed_whitelist_kosong_tapi_id_dibatasi(tmp_env, monkeypatch):
    """Whitelist kosong tapi TELEGRAM_ALLOWED_IDS terisi -> hanya ID itu."""
    from app import config
    from app.bots import telegram_bot as tb

    monkeypatch.setattr(config, "TELEGRAM_ALLOWED_IDS", {42})
    monkeypatch.setattr(tb, "_whitelist_numbers", lambda: set())
    assert tb._allowed(42) is True
    assert tb._allowed(7) is False


def test_allowed_fail_closed_saat_whitelist_tidak_diketahui(tmp_env, monkeypatch):
    """Status whitelist tidak diketahui -> akses TERTUTUP (bukan terbuka)."""
    from app.bots import telegram_bot as tb

    monkeypatch.setattr(tb, "_whitelist_numbers", lambda: None)
    tb._verified = {}
    assert tb._allowed(7) is False


def test_whitelist_numbers_none_saat_bridge_gagal(tmp_env, monkeypatch):
    """Fetch whitelist gagal & belum ada cache -> None (fail closed)."""
    monkeypatch.undo()  # pulihkan _whitelist_numbers asli (hapus patch fixture)
    from app.bots import telegram_bot as tb

    monkeypatch.setattr(
        whitelist, "wa_whitelist_list", lambda: {"ok": False, "error": "bridge mati"}
    )
    tb._whitelist_cache = None
    assert tb._whitelist_numbers() is None


def test_whitelist_numbers_cache_setelah_fetch_berhasil(tmp_env, monkeypatch):
    """Fetch berhasil -> daftar nomor dipakai sebagai cache."""
    monkeypatch.undo()
    from app.bots import telegram_bot as tb

    monkeypatch.setattr(
        whitelist, "wa_whitelist_list", lambda: {"ok": True, "allowed": ["6281111111111"]}
    )
    tb._whitelist_cache = None
    assert tb._whitelist_numbers() == {"6281111111111"}


def test_deny_minta_bagikan_nomor_saat_whitelist_aktif(tmp_env, monkeypatch):
    """User tanpa akses diminta membagikan nomor (tombol request_contact)."""
    from app.bots import telegram_bot as tb

    monkeypatch.setattr(tb, "_whitelist_numbers", lambda: {"628123456789"})
    replies = []

    async def reply_text(*a, **k):
        replies.append((a, k))

    update = types.SimpleNamespace(
        effective_user=types.SimpleNamespace(id=7),
        message=types.SimpleNamespace(reply_text=reply_text),
    )
    _run(tb._deny_or_request_contact(update))
    assert replies and "whitelist" in replies[0][0][0]
    btn = replies[0][1]["reply_markup"].keyboard[0][0]
    assert btn.request_contact is True


def test_deny_tanpa_whitelist_tolak_biasa(tmp_env, monkeypatch):
    """Tanpa whitelist aktif (hanya ID dibatasi) -> tolak tanpa minta nomor."""
    from app.bots import telegram_bot as tb

    monkeypatch.setattr(tb, "_whitelist_numbers", lambda: set())
    replies = []

    async def reply_text(*a, **k):
        replies.append((a, k))

    update = types.SimpleNamespace(
        effective_user=types.SimpleNamespace(id=7),
        message=types.SimpleNamespace(reply_text=reply_text),
    )
    _run(tb._deny_or_request_contact(update))
    assert replies and "tidak punya akses" in replies[0][0][0]


def test_contact_nomor_terdaftar_diberi_akses(tmp_env, monkeypatch, tmp_path):
    """Nomor yang dibagikan & cocok dengan whitelist -> akses dibuka + disimpan."""
    from app.bots import telegram_bot as tb

    monkeypatch.setattr(tb, "_whitelist_numbers", lambda: {"628123456789"})
    tb._verified = {}

    update, replies = _contact_update("+62 812-3456-789")
    context = types.SimpleNamespace(user_data={})
    _run(tb._contact(update, context))
    assert tb._verified.get("7") == "628123456789"
    assert replies and "terdaftar" in replies[0][0][0]
    # daftar user terverifikasi tersimpan persisten di data/
    assert (tmp_path / "telegram_verified.json").exists()


def test_contact_nomor_tidak_terdaftar_ditolak(tmp_env, monkeypatch):
    """Nomor yang dibagikan tidak ada di whitelist -> ditolak."""
    from app.bots import telegram_bot as tb

    monkeypatch.setattr(tb, "_whitelist_numbers", lambda: {"628123456789"})
    tb._verified = {}

    update, replies = _contact_update("+6280000000000")
    context = types.SimpleNamespace(user_data={})
    _run(tb._contact(update, context))
    assert "7" not in tb._verified
    assert replies and "whitelist" in replies[0][0][0]


def test_contact_mode_terbuka_tanpa_verifikasi(tmp_env, monkeypatch):
    """Whitelist kosong -> membagikan nomor tidak mengunci siapa pun."""
    from app.bots import telegram_bot as tb

    monkeypatch.setattr(tb, "_whitelist_numbers", lambda: set())
    tb._verified = {}

    update, replies = _contact_update("+6280000000000")
    context = types.SimpleNamespace(user_data={})
    _run(tb._contact(update, context))
    assert "7" not in tb._verified  # tidak perlu diverifikasi
    assert replies and "terbuka" in replies[0][0][0]


def test_save_verified_persisten_setelah_load(tmp_env, monkeypatch, tmp_path):
    """User terverifikasi tetap diingat setelah proses baru membaca file."""
    from app.bots import telegram_bot as tb

    tb._verified = {}
    tb._save_verified(7, "628123456789")
    # simulasi restart: baca ulang dari disk
    tb._verified = {}
    tb._load_verified()
    assert tb._verified.get("7") == "628123456789"
