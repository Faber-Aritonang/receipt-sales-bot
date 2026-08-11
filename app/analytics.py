"""Analisa data penjualan berbasis pandas (membaca dari SQLite)."""
from __future__ import annotations

import pandas as pd

from . import database as db

_DATE_FMT = "%d %b %Y"

# ---------------------------------------------------------------- agregasi


def _receipts_df() -> pd.DataFrame:
    return db.query_df("SELECT * FROM receipts WHERE total IS NOT NULL")


def _effective_dates(df: pd.DataFrame) -> pd.Series:
    """Tanggal efektif tiap struk.

    Bila OCR tidak bisa membaca tanggal struk (receipt_date kosong), struk
    dianggap terjadi pada tanggal upload (created_at) — biasanya hari ini,
    sehingga laporan harian tidak menampilkan "0 struk" untuk data baru.
    """
    d = df["receipt_date"].fillna("").astype(str).str.strip()
    fallback = df["created_at"].fillna("").astype(str).str[:10]
    return d.mask(d.isin(["", "None"]), fallback)


def summary() -> dict:
    """Ringkasan menyeluruh: total, rata-rata, hari ini, bulan ini vs bulan lalu."""
    df = _receipts_df()
    today = db.today_iso()
    out: dict = {
        "total_receipts": int(len(df)),
        "total_revenue": float(df["total"].sum()) if len(df) else 0.0,
        "avg_per_receipt": float(df["total"].mean()) if len(df) else 0.0,
        "today_count": 0,
        "today_revenue": 0.0,
        "month_revenue": 0.0,
        "prev_month_revenue": 0.0,
        "month_growth_pct": 0.0,
    }
    if len(df):
        eff = _effective_dates(df)
        today_df = df[eff == today]
        out["today_count"] = int(len(today_df))
        out["today_revenue"] = float(today_df["total"].sum())
        month = today[:7]
        cur = df[eff.str.startswith(month)]
        out["month_revenue"] = float(cur["total"].sum())
        ym = pd.to_datetime(today + "-01") - pd.DateOffset(months=1)
        prev = ym.strftime("%Y-%m")
        prev_df = df[eff.str.startswith(prev)]
        out["prev_month_revenue"] = float(prev_df["total"].sum())
        if out["prev_month_revenue"]:
            out["month_growth_pct"] = round(
                (out["month_revenue"] - out["prev_month_revenue"])
                / out["prev_month_revenue"]
                * 100,
                1,
            )
    return out


def daily_series(days: int = 30) -> dict:
    """Deret penjualan per hari (untuk grafik)."""
    df = _receipts_df()
    if len(df) == 0:
        return {"dates": [], "revenue": [], "count": []}
    df["receipt_date"] = _effective_dates(df)
    end = pd.Timestamp.today().normalize()
    start = end - pd.Timedelta(days=days - 1)
    g = (
        df.groupby("receipt_date")
        .agg(revenue=("total", "sum"), count=("total", "size"))
        .reset_index()
    )
    all_days = pd.DataFrame({"receipt_date": pd.date_range(start, end).strftime("%Y-%m-%d")})
    merged = all_days.merge(g, on="receipt_date", how="left").fillna(0)
    return {
        "dates": merged["receipt_date"].tolist(),
        "revenue": merged["revenue"].round(0).astype(int).tolist(),
        "count": merged["count"].astype(int).tolist(),
    }


def top_products(limit: int = 10) -> list[dict]:
    """Produk terlaris dari tabel items."""
    rows = db.query(
        """
        SELECT LOWER(TRIM(name)) AS key, name,
               SUM(qty) AS qty, SUM(total_price) AS revenue
        FROM items WHERE name IS NOT NULL AND name != ''
        GROUP BY key
        ORDER BY revenue DESC LIMIT ?
        """,
        (limit,),
    )
    seen = {}
    for r in rows:
        key = r["key"]
        if key in seen:
            continue
        seen[key] = r
    return [{"name": r["name"], "qty": float(r["qty"] or 0), "revenue": float(r["revenue"] or 0)}
            for r in seen.values()]


def payment_breakdown() -> list[dict]:
    """Total & jumlah struk per metode pembayaran."""
    df = _receipts_df()
    if len(df) == 0:
        return []
    g = (
        df.groupby(df["payment_method"].fillna("Tidak diketahui"))
        .agg(revenue=("total", "sum"), count=("total", "size"))
        .reset_index()
        .sort_values("revenue", ascending=False)
    )
    return [
        {"method": r["payment_method"], "revenue": float(r["revenue"]), "count": int(r["count"])}
        for r in g.to_dict("records")
    ]


def hourly_series(day: str | None = None) -> list[dict]:
    """Penjualan per jam (jam struk masuk/dicetak).

    day diberikan -> hanya struk dengan tanggal efektif = day (untuk laporan harian).
    """
    df = db.query_df(
        "SELECT receipt_date, receipt_time, total, created_at FROM receipts WHERE total IS NOT NULL"
    )
    if len(df) == 0:
        return []
    if day:
        df = df[_effective_dates(df) == day]
    df = df[df["receipt_time"].notna()].copy()
    df["hour"] = df["receipt_time"].str.split(":").str[0].astype(int)
    g = df.groupby("hour").agg(revenue=("total", "sum"), count=("total", "size")).reset_index()
    full = pd.DataFrame({"hour": range(0, 24)}).merge(g, on="hour", how="left").fillna(0)
    return [
        {"hour": int(r["hour"]), "revenue": float(r["revenue"]), "count": int(r["count"])}
        for r in full.to_dict("records")
    ]


def recent(limit: int = 15) -> list[dict]:
    rows = db.recent_receipts(limit)
    out = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "source": r["source"],
                "merchant": r["merchant"] or "-",
                "date": r["receipt_date"] or "-",
                "time": r["receipt_time"] or "-",
                "total": r["total"],
                "payment_method": r["payment_method"] or "-",
                "confidence": r["ocr_confidence"] or "-",
            }
        )
    return out


# ---------------------------------------------------------------- teks laporan

def _money(v: float) -> str:
    return f"Rp {v:,.0f}".replace(",", ".")


def report_daily() -> str:
    s = summary()
    h = hourly_series(day=db.today_iso())
    lines = ["📆 *LAPORAN HARIAN*", ""]
    lines.append(f"📊 Total hari ini: {s['today_count']} struk")
    lines.append(f"💰 Pendapatan hari ini: {_money(s['today_revenue'])}")
    if h:
        top_hours = sorted(h, key=lambda x: x["revenue"], reverse=True)[:3]
        jam = ", ".join(f"{r['hour']:02d}.00 ({_money(r['revenue'])})" for r in top_hours if r["revenue"] > 0)
        if jam:
            lines.append(f"🕐 Jam tersibuk: {jam}")
    lines.append("")
    lines.append(f"🏷️ Rata-rata per struk: {_money(s['avg_per_receipt'])}")
    return "\n".join(lines)


def report_weekly() -> str:
    df = db.query_df(
        "SELECT receipt_date, total, created_at FROM receipts WHERE total IS NOT NULL"
    )
    lines = ["🗓️ *LAPORAN 7 HARI TERAKHIR*", ""]
    if len(df) == 0:
        lines.append("Belum ada data penjualan.")
        return "\n".join(lines)
    df["receipt_date"] = _effective_dates(df)
    end = pd.Timestamp.today().normalize()
    start = end - pd.Timedelta(days=6)
    g = df.groupby("receipt_date")["total"].sum().reset_index()
    days = pd.DataFrame({"receipt_date": pd.date_range(start, end).strftime("%Y-%m-%d")})
    merged = days.merge(g, on="receipt_date", how="left").fillna(0)
    total = 0.0
    for _, r in merged.iterrows():
        day = pd.Timestamp(r["receipt_date"]).strftime("%a, %d %b")
        total += float(r["total"])
        lines.append(f"• {day}: {_money(float(r['total']))}")
    lines.append("")
    lines.append(f"💰 Total 7 hari: {_money(total)}")
    return "\n".join(lines)


def report_monthly() -> str:
    s = summary()
    top = top_products(5)
    lines = ["📅 *LAPORAN BULAN INI*", ""]
    lines.append(f"💰 Pendapatan bulan ini: {_money(s['month_revenue'])}")
    lines.append(f"📈 vs bulan lalu: {s['month_growth_pct']:+.1f}%")
    lines.append(f"🧾 Jumlah struk: {s['total_receipts']} (total semua data)")
    lines.append("")
    lines.append("🏆 *Produk terlaris:*")
    if top:
        for i, p in enumerate(top[:5], 1):
            lines.append(f"{i}. {p['name']} — {_money(p['revenue'])} ({int(p['qty'])} pcs)")
    else:
        lines.append("Belum ada data produk.")
    return "\n".join(lines)


def report_top_products() -> str:
    top = top_products(10)
    lines = ["🏆 *PRODUK TERLARIS*", ""]
    if not top:
        lines.append("Belum ada data produk.")
        return "\n".join(lines)
    for i, p in enumerate(top, 1):
        lines.append(f"{i}. {p['name']}")
        lines.append(f"   {_money(p['revenue'])} · {int(p['qty'])} pcs")
    return "\n".join(lines)


def report_total() -> str:
    s = summary()
    lines = [
        "💼 *RINGKASAN TOTAL*",
        "",
        f"🧾 Jumlah struk tersimpan: {s['total_receipts']}",
        f"💰 Total pendapatan: {_money(s['total_revenue'])}",
        f"🏷️ Rata-rata per struk: {_money(s['avg_per_receipt'])}",
        f"📆 Hari ini: {_money(s['today_revenue'])} ({s['today_count']} struk)",
    ]
    return "\n".join(lines)
