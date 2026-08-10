"""Parser teks struk belanja Indonesia menjadi data terstruktur.

Bekerja pada output OCR (teks mentah). Output OCR sering memecah baris:
- nama item di baris 1, harga di baris berikutnya
- kata kunci (TOTAL/SUBTOTAL) di baris 1, angkanya di baris berikutnya
Parser ini menggabungkan kembali pasangan tersebut secara heuristik.
"""
from __future__ import annotations

import re
from datetime import datetime

# ---------- pola ----------
_DATE_RE = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b")
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b")
_RP_RE = re.compile(r"(?:\bRp\.?\s*)?\d[\d\.,]*")
_QTYX_RE = re.compile(r"(\d{1,3})\s*[xX*]\s*")

TOTAL_KEYWORDS = ("TOTAL", "GRAND TOTAL", "TOTAL BAYAR", "TOTAL TAGIHAN", "TOTAL PEMBAYARAN")
SUBTOTAL_KEYWORDS = ("SUBTOTAL", "SUB TOTAL", "TOTAL BELANJA", "TOTAL HARGA")
TAX_KEYWORDS = ("PPN", "PAJAK", "PB1", "PB 1", "SVC", "SERVICE", "LAYANAN")
PAYMENT_KEYWORDS = (
    "TUNAI", "CASH", "DEBIT", "KREDIT", "QRIS", "OVO", "GOPAY", "DANA",
    "SHOPEEPAY", "E-WALLET", "EWALLET", "KARTU", "SALDO", "KEMBALI", "CHANGE",
)
_SEP_RE = re.compile(r"^[\-\._=*\s]{3,}$")
_ADDRESS_RE = re.compile(r"\b(jl\.?|jalan|no\.?\s*\d+|telp|hp|npwp|p\.?\s*o\.?\s*b\.?)\b", re.IGNORECASE)

_NORMALIZE_NAMES = {
    "DEBIT": "Kartu Debit",
    "KREDIT": "Kartu Kredit",
    "TUNAI": "Tunai",
    "CASH": "Tunai",
    "QRIS": "QRIS",
    "OVO": "OVO",
    "GOPAY": "GoPay",
    "DANA": "DANA",
    "SHOPEEPAY": "ShopeePay",
    "E-WALLET": "E-Wallet",
    "EWALLET": "E-Wallet",
    "SALDO": "E-Wallet",
    "KEMBALI": "Kembalian",
    "CHANGE": "Kembalian",
}


def _clean(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def is_separator(line: str) -> bool:
    """Baris pemisah: ------, .........., atau noise OCR seperti ..c.cccccc."""
    if _SEP_RE.match(line):
        return True
    letters = re.findall(r"[A-Za-z]", line)
    if len(letters) >= 4 and len(set(l.upper() for l in letters)) <= 2:
        return True  # satu-dua huruf berulang -> noise, bukan teks
    core = re.sub(r"[^A-Za-z0-9]", "", line)
    return len(core) <= 2


def parse_amount(text: str):
    """Ambil angka uang ala Indonesia dari sebuah string -> float | None."""
    m = _RP_RE.search(text)
    if not m:
        return None
    raw = m.group(0).replace("Rp.", "").replace("Rp", "").strip()
    normalized = re.sub(r"\.(?=\d{3}(?:[.,]|\s|$))", "", raw).replace(",", ".")
    try:
        val = float(normalized)
        return val if val > 0 else None
    except ValueError:
        return None


def _all_amounts(line: str) -> list[float]:
    return [a for a in (parse_amount(m.group(0)) for m in _RP_RE.finditer(line)) if a]


def _price_amount(line: str) -> float | None:
    """Harga pada baris item = angka terakhir yang 'berbentuk harga'.

    Angka seperti ukuran (5kg, 1kg, 2L) tidak dianggap harga karena melekat
    pada huruf. Harga harus di ujung baris, >= 1000, atau angka utuh >= 4 digit,
    atau berdiri sendiri (dipisah spasi).
    """
    best = None
    for m in _RP_RE.finditer(line):
        a = parse_amount(m.group(0))
        if a is None:
            continue
        before = line[: m.start()]
        after = line[m.end():]
        if after.strip():  # angka bukan di ujung baris (mis. "5kg", "2 x 15000"->"2")
            continue
        digits = re.sub(r"\D", "", m.group(0))
        if a >= 1000 or len(digits) >= 4 or (before and before[-1].isspace()):
            best = a
    return best


def _norm_date(d: str, mo: str, y: str) -> str | None:
    try:
        dd, mm, yy = int(d), int(mo), int(y)
        year = 2000 + yy if yy < 100 else yy
        return datetime(year, mm, dd).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _keyword_kind(line: str) -> tuple[str, str] | None:
    """Jenis kata kunci pada baris ('total'/'subtotal'/'tax'/'payment') + kata aslinya."""
    up = line.upper()
    for k in SUBTOTAL_KEYWORDS:
        if k in up:
            return "subtotal", k
    for k in TOTAL_KEYWORDS:
        if re.search(r"(?<!SUB)\b" + re.escape(k) + r"\b", up):
            return "total", k
    for k in TAX_KEYWORDS:
        if k in up:
            return "tax", k
    for k in PAYMENT_KEYWORDS:
        if k in up and k not in ("KEMBALI", "CHANGE"):
            return "payment", k
    return None


def _keyword_amount(lines: list[str], i: int) -> float | None:
    """Angka yang terasosiasi dengan baris kata kunci di index i.

    Prioritas: (1) angka di baris yang sama, (2) angka di 1-2 baris berikutnya
    (lewati baris pemisah & baris kata kunci tanpa angka). Untuk kata kunci
    pajak, angka kecil di baris yang sama dianggap persentase ("PPN 11%").
    """
    line = lines[i]
    same = _all_amounts(line)
    if "%" in line and same and same[-1] < 1000:
        same = []  # "PPN 11%" -> persentase, ambil dari baris berikutnya
    if same:
        return same[-1]
    for j in (i + 1, i + 2):
        if j >= len(lines) or is_separator(lines[j]):
            break
        cand = lines[j]
        kind = _keyword_kind(cand)
        if kind and kind[0] in ("payment", "tax"):
            # jangan sampai TOTAL mengambil nominal pembayaran/pajak
            break
        if kind and not _all_amounts(cand):
            continue
        amts = _all_amounts(cand)
        if amts:
            return amts[-1]
    return None


def _clean_item_name(line: str, qty_m) -> str:
    """Nama item dari satu baris: buang pola qty-harga & angka harga di ujung."""
    name = line
    if qty_m:
        name = re.sub(r"\s*\d{1,3}\s*[xX*]\s*[\d\.,]+\s*$", "", name)
    name = re.sub(r"\s*[\d\.,]{2,}\s*$", "", name)  # harga di ujung baris
    name = re.sub(r"\s+", " ", name).strip(" -–—:;")
    return name


def _extract_items(lines: list[str]) -> list[dict]:
    """Item dari area antara header dan area total. Gabungkan baris nama+harga."""
    items: list[dict] = []
    pending: list[str] = []

    for line in lines:
        if is_separator(line) or _ADDRESS_RE.search(line) or _DATE_RE.search(line) or _TIME_RE.search(line):
            pending = []
            continue
        kind = _keyword_kind(line)
        if kind and kind[0] in ("total", "subtotal"):
            break  # selesai, area total dimulai
        if kind:
            pending = []
            continue

        price = _price_amount(line)
        if price is not None:
            total_price = price
            qty_m = _QTYX_RE.search(line)
            qty = float(qty_m.group(1)) if qty_m else 1.0
            if qty_m:
                unit = parse_amount(line[qty_m.end():])
                if unit is not None:
                    total_price = qty * unit
            name = _clean_item_name(line, qty_m)
            if pending:
                # nama item biasanya di baris SEBELUM baris harga
                name = " ".join(pending + ([name] if name else [])).strip()
                pending = []
            if name and len(name) >= 2:
                items.append({
                    "name": name,
                    "qty": qty,
                    "unit_price": (total_price / qty) if qty_m and qty else None,
                    "total_price": total_price,
                })
        else:
            if line:
                pending.append(line)

    return items


def parse_receipt(raw_text: str) -> dict:
    """Ubah teks OCR menjadi struktur data terurai."""
    lines = [_clean(l) for l in raw_text.splitlines()]
    lines = [l for l in lines if l]

    result: dict = {
        "merchant": None,
        "receipt_date": None,
        "receipt_time": None,
        "subtotal": None,
        "tax": None,
        "total": None,
        "payment_method": None,
        "items": [],
        "confidence": "sedang",
    }

    # ---- tanggal & jam (di baris mana pun) ----
    for line in lines:
        dm = _DATE_RE.search(line)
        if dm and not result["receipt_date"]:
            result["receipt_date"] = _norm_date(dm.group(1), dm.group(2), dm.group(3))
        tm = _TIME_RE.search(line)
        if tm and not result["receipt_time"]:
            result["receipt_time"] = f"{int(tm.group(1)):02d}:{tm.group(2)}"

    # ---- merchant: baris pertama yang bukan tanggal/alamat/separator ----
    for line in lines:
        if is_separator(line) or _ADDRESS_RE.search(line):
            continue
        if _DATE_RE.search(line) and len(line) < 30:
            continue
        if len(line) < 3 or line.upper().startswith(("TOTAL", "JUMLAH", "KASIR")):
            continue
        result["merchant"] = line
        break

    # ---- subtotal / pajak / total / pembayaran ----
    for i, line in enumerate(lines):
        kind = _keyword_kind(line)
        if kind is None:
            continue
        kind_name, _kw = kind
        amt = _keyword_amount(lines, i)
        if kind_name == "total" and amt is not None and result["total"] is None:
            result["total"] = amt
        elif kind_name == "subtotal" and amt is not None and result["subtotal"] is None:
            result["subtotal"] = amt
        elif kind_name == "tax" and amt is not None and result["tax"] is None:
            result["tax"] = amt
        elif kind_name == "payment" and result["payment_method"] is None:
            up = line.upper()
            for k in PAYMENT_KEYWORDS:
                if k in up and k not in ("KEMBALI", "CHANGE"):
                    result["payment_method"] = _NORMALIZE_NAMES.get(k, k.title())
                    break

    # Fallback pembayaran: cari kata kunci bayar di baris mana pun
    if result["payment_method"] is None:
        for line in lines:
            up = line.upper()
            for k in PAYMENT_KEYWORDS:
                if k in up and k not in ("KEMBALI", "CHANGE"):
                    result["payment_method"] = _NORMALIZE_NAMES.get(k, k.title())
                    break
            if result["payment_method"]:
                break

    result["items"] = _extract_items(lines)

    # ---- confidence ----
    found = sum(1 for v in (result["total"], result["receipt_date"], result["merchant"]) if v)
    if found >= 3 and result["total"]:
        result["confidence"] = "tinggi"
    elif found >= 1:
        result["confidence"] = "sedang"
    else:
        result["confidence"] = "rendah"

    return result
