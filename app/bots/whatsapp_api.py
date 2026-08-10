"""Webhook untuk bridge WhatsApp (Node.js + Baileys).

Bridge mengirim multipart/form-data ke /api/whatsapp/inbound:
- type=image -> file `image` (+ sender, caption)
- type=text  -> field `text` (+ sender)

Server membalas JSON {reply: "..."} yang akan dikirim bridge ke pengguna.
"""
from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .. import config, process

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


@router.post("/inbound")
def inbound(
    sender: str = Form(...),
    type: str = Form(...),
    text: str = Form(""),
    caption: str = Form(""),
    secret: str = Form(...),
    image: UploadFile | None = File(None),
) -> dict:
    # handler sync agar OCR (lambat) tidak memblokir event loop FastAPI
    if not secrets.compare_digest(secret, config.BRIDGE_WEBHOOK_SECRET):
        raise HTTPException(status_code=403, detail="secret salah")

    try:
        if type == "image" and image is not None:
            data = image.file.read()
            result = process.handle_image(data, source="whatsapp", sender_id=sender)
            return {"reply": result["reply"]}
        elif type == "text":
            return {"reply": process.command_reply(text, sender_id=sender)}
        return {"reply": "❓ Kirim foto struk untuk mencatat penjualan."}
    except Exception as exc:  # pragma: no cover
        log.exception("gagal memproses pesan whatsapp")
        return {"reply": f"⚠️ Terjadi kesalahan internal: {exc}"}


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
