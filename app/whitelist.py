"""Kelola whitelist nomor WhatsApp melalui bridge (endpoint /admin/whitelist).

Dipakai oleh perintah bot Telegram: /izinkan, /blokir, /whitelist.
Bridge menyimpan daftar ke whatsapp-bridge/allowed-numbers.json (persisten).
"""
from __future__ import annotations

import json
import logging
import urllib.request

from . import config

log = logging.getLogger(__name__)

_HEADERS = {"Content-Type": "application/json"}


def _call(action: str, number: str | None = None) -> dict:
    """Kirim permintaan ke endpoint admin bridge. Mengembalikan dict respons."""
    payload = json.dumps({"action": action, "number": number}).encode("utf-8")
    req = urllib.request.Request(
        f"{config.BRIDGE_URL}/admin/whitelist",
        data=payload,
        headers={**_HEADERS, "x-secret": config.BRIDGE_WEBHOOK_SECRET},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # pragma: no cover - jaringannya fluktuatif
        log.warning("gagal hubungi bridge /admin/whitelist: %s", exc)
        return {"ok": False, "error": f"bridge tidak merespons: {exc}"}


def wa_whitelist_add(number: str) -> dict:
    """Tambahkan nomor (format bebas, akan dinormalisasi bridge)."""
    return _call("add", number)


def wa_whitelist_remove(number: str) -> dict:
    """Hapus nomor dari whitelist."""
    return _call("remove", number)


def wa_whitelist_list() -> dict:
    """Ambil daftar nomor yang saat ini diizinkan."""
    return _call("list")
