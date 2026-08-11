"""Backup otomatis database SQLite.

Menggunakan API backup bawaan sqlite3 sehingga aman dipanggil kapan pun
(termasuk saat DB sedang dibaca/ditulis, mode WAL). Backup disimpan di
`data/backup/sales_YYYY-MM-DD_HHMMSS.db`. Backup lama (lebih dari
BACKUP_KEEP_DAYS hari) dibersihkan otomatis.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

BACKUP_KEEP_DAYS = int(config.BACKUP_KEEP_DAYS)
_BACKUP_RE = re.compile(r"^sales_(\d{4}-\d{2}-\d{2})_.*\.db$")


def backup_dir() -> Path:
    d = Path(config.DATA_DIR) / "backup"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _backup_path() -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return backup_dir() / f"sales_{stamp}.db"


def backup_now() -> Path:
    """Buat satu backup DB sekarang. Mengembalikan path file backup."""
    src = Path(config.DB_PATH)
    if not src.exists():
        log.warning("backup dilewati: %s belum ada", src)
        raise FileNotFoundError(src)

    dst = _backup_path()
    # API backup sqlite3 menyalin ke file tujuan dengan aman (konsisten walau
    # ada koneksi lain; tidak butuh menghentikan server).
    with sqlite3.connect(str(src)) as src_conn:
        with sqlite3.connect(str(dst)) as dst_conn:
            src_conn.backup(dst_conn)
    log.info("backup DB -> %s", dst)
    return dst


def backup_if_due() -> Path | None:
    """Backup jika belum ada backup hari ini (dipanggil saat server start).

    Mengembalikan path backup yang dibuat, atau None jika sudah ada backup
    hari ini (tidak ada yang dibuat).
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if list(backup_dir().glob(f"sales_{today}_*.db")):
        return None  # sudah ada backup hari ini
    return backup_now()


def prune_old_backups(keep_days: int = BACKUP_KEEP_DAYS) -> list[Path]:
    """Hapus backup yang lebih tua dari keep_days. Mengembalikan file terhapus."""
    cutoff = (datetime.now().timestamp() - keep_days * 86400)
    removed: list[Path] = []
    for p in backup_dir().glob("sales_*.db"):
        m = _BACKUP_RE.match(p.name)
        if not m:
            continue
        try:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d").timestamp()
        except ValueError:
            continue
        if ts < cutoff:
            try:
                p.unlink()
                removed.append(p)
            except OSError:
                log.warning("gagal hapus backup %s", p)
    if removed:
        log.info("backup lama dibersihkan: %d file", len(removed))
    return removed


def run_backup() -> tuple[Path | None, list[Path]]:
    """Backup bila belum ada hari ini + bersihkan yang lama.

    Cocok dipanggil di cron, saat server start, atau loop terjadwal.
    Mengembalikan (file_backup_baru_atau_None, daftar_yang_dihapus).
    """
    created = None
    try:
        created = backup_if_due()
    except Exception:  # pragma: no cover - kegagalan backup tidak boleh mematikan server
        log.exception("gagal membuat backup")
    removed = prune_old_backups()
    return created, removed


if __name__ == "__main__":
    # Jalankan manual: .venv/bin/python -m app.backup
    start = time.time()
    created, removed = run_backup()
    print(f"backup baru : {created or '(sudah ada hari ini)'}")
    print(f"dihapus     : {len(removed)} file")
    print(f"waktu       : {time.time() - start:.2f}s")
