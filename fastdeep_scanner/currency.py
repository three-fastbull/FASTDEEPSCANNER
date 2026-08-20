"""Reporting and trading currency handling.

Two currencies matter for every symbol and they are not always the same:

* trading currency  - the currency the price feed quotes (THB for ``.BK``, HKD for ``.HK``)
* reporting currency - the currency the financial statements are filed in

A stock can be listed in HKD but report in CNY. Mixing them silently produces a
wrong P/E, so valuation is only marked verified when the two currencies match or
a dated FX rate is available to convert one into the other.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FX_PATH = ROOT / "data" / "fastdeep_fx_rates.json"

SUFFIX_CURRENCY: dict[str, str] = {
    ".BK": "THB",
    ".HK": "HKD",
    ".SS": "CNY",
    ".SZ": "CNY",
    ".T": "JPY",
    ".KS": "KRW",
    ".KQ": "KRW",
    ".TW": "TWD",
    ".TWO": "TWD",
    ".SI": "SGD",
    ".NS": "INR",
    ".BO": "INR",
    ".AX": "AUD",
    ".TO": "CAD",
    ".V": "CAD",
    ".L": "GBP",
    ".DE": "EUR",
    ".F": "EUR",
    ".PA": "EUR",
    ".AS": "EUR",
    ".MI": "EUR",
    ".MC": "EUR",
    ".BR": "EUR",
    ".LS": "EUR",
    ".HE": "EUR",
    ".VI": "EUR",
    ".SW": "CHF",
    ".ST": "SEK",
    ".OL": "NOK",
    ".CO": "DKK",
    ".SA": "BRL",
    ".MX": "MXN",
    ".JO": "ZAR",
}

MARKET_CURRENCY: dict[str, str] = {
    "US": "USD",
    "TH": "THB",
    "CN": "CNY",
    "HK": "HKD",
    "JP": "JPY",
    "SG": "SGD",
    "KR": "KRW",
    "TW": "TWD",
    "IN": "INR",
    "UK": "GBP",
    "GB": "GBP",
    "EU": "EUR",
    "AU": "AUD",
    "CA": "CAD",
}

CURRENCY_NAMES_TH: dict[str, str] = {
    "USD": "ดอลลาร์สหรัฐ",
    "THB": "บาท",
    "HKD": "ดอลลาร์ฮ่องกง",
    "CNY": "หยวนจีน",
    "JPY": "เยนญี่ปุ่น",
    "EUR": "ยูโร",
    "GBP": "ปอนด์สเตอร์ลิง",
    "SGD": "ดอลลาร์สิงคโปร์",
    "TWD": "ดอลลาร์ไต้หวัน",
    "KRW": "วอนเกาหลี",
    "INR": "รูปีอินเดีย",
    "AUD": "ดอลลาร์ออสเตรเลีย",
    "CAD": "ดอลลาร์แคนาดา",
    "CHF": "ฟรังก์สวิส",
    "SEK": "โครนาสวีเดน",
    "NOK": "โครนนอร์เวย์",
    "DKK": "โครนเดนมาร์ก",
    "BRL": "เรียลบราซิล",
    "MXN": "เปโซเม็กซิโก",
    "ZAR": "แรนด์แอฟริกาใต้",
}


def trading_currency(symbol: str, market: str = "") -> str:
    """Currency the exchange quotes this symbol in."""
    text = (symbol or "").strip().upper()
    if "." in text:
        suffix = text[text.rindex(".") :]
        if suffix in SUFFIX_CURRENCY:
            return SUFFIX_CURRENCY[suffix]
    return MARKET_CURRENCY.get((market or "").strip().upper(), "USD")


def price_scale(symbol: str) -> float:
    """London quotes in pence while statements are filed in pounds."""
    return 0.01 if (symbol or "").strip().upper().endswith(".L") else 1.0


def currency_name_th(code: str) -> str:
    code = (code or "").strip().upper()
    return CURRENCY_NAMES_TH.get(code, code or "-")


def currency_label(code: str) -> str:
    """``USD`` -> ``USD (ดอลลาร์สหรัฐ)`` so the unit is never ambiguous on screen."""
    code = (code or "").strip().upper()
    if not code:
        return "ไม่ทราบสกุลเงิน"
    name = CURRENCY_NAMES_TH.get(code)
    return f"{code} ({name})" if name else code


def load_fx_rates(path: str | Path = DEFAULT_FX_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"rates": {}, "base": "USD", "updated_at": None}
    payload.setdefault("rates", {})
    payload.setdefault("base", "USD")
    return payload


def convert(
    amount: float,
    source: str,
    target: str,
    rates: dict[str, float] | None = None,
) -> float | None:
    """Convert through the USD base. Returns ``None`` when a leg has no rate."""
    source = (source or "").strip().upper()
    target = (target or "").strip().upper()
    if not source or not target:
        return None
    if source == target:
        return amount
    rates = rates if rates is not None else load_fx_rates().get("rates", {})
    per_usd_source = 1.0 if source == "USD" else rates.get(source)
    per_usd_target = 1.0 if target == "USD" else rates.get(target)
    if not per_usd_source or not per_usd_target:
        return None
    return amount / per_usd_source * per_usd_target


def to_usd(amount: float, source: str, rates: dict[str, float] | None = None) -> float | None:
    return convert(amount, source, "USD", rates)


def fx_age_days(path: str | Path = DEFAULT_FX_PATH) -> float | None:
    payload = load_fx_rates(path)
    updated = payload.get("updated_at")
    if not updated:
        return None
    try:
        stamp = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return (datetime.now(UTC) - stamp).total_seconds() / 86400
