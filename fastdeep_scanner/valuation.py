"""P/E and P/BV derived from filed statements and the live price.

Both legs must be expressed in the same currency. A stock quoted in HKD that
files in CNY produces a meaningless multiple unless the price is converted
first, so valuation stays unverified whenever that conversion is not possible.
"""

from __future__ import annotations

from typing import Any

from .currency import convert, currency_label, price_scale
from .models import FundamentalSnapshot


def derive_valuation(
    snapshot: FundamentalSnapshot,
    last_price: float,
    rates: dict[str, float] | None = None,
) -> dict[str, Any]:
    trading = (snapshot.trading_currency or "").upper()
    reporting = (snapshot.reporting_currency or "").upper()
    result: dict[str, Any] = {
        "pe": None,
        "pbv": None,
        "eps": snapshot.eps or None,
        "book_value_per_share": snapshot.book_value_per_share or None,
        "upside_pct": None,
        "fair_value": snapshot.analyst_fair_value or None,
        "trading_currency": trading,
        "reporting_currency": reporting,
        "fx_adjusted": False,
        "fx_rate": None,
        "verified": False,
        "note": "",
    }

    if snapshot.analyst_fair_value and last_price:
        result["upside_pct"] = round((snapshot.analyst_fair_value / last_price - 1) * 100, 2)

    if not snapshot.fundamentals_verified:
        result["note"] = "ยังไม่ได้ตรวจงบการเงิน จึงคำนวณ P/E และ P/BV ไม่ได้"
        return result
    if not reporting:
        result["note"] = "งบการเงินไม่ระบุสกุลเงิน จึงเทียบกับราคาหุ้นไม่ได้"
        return result
    if last_price <= 0:
        result["note"] = "ไม่มีราคาปิดล่าสุด"
        return result

    quoted_price = last_price * price_scale(snapshot.symbol)
    if trading == reporting:
        price_in_reporting: float | None = quoted_price
    else:
        price_in_reporting = convert(quoted_price, trading, reporting, rates)
        if price_in_reporting is None:
            result["note"] = (
                f"ราคาซื้อขายเป็น {currency_label(trading)} แต่งบเป็น {currency_label(reporting)} "
                "และไม่มีอัตราแลกเปลี่ยน จึงไม่ประกาศ P/E และ P/BV"
            )
            return result
        result["fx_adjusted"] = True
        result["fx_rate"] = round(price_in_reporting / quoted_price, 6) if quoted_price else None

    if snapshot.eps and snapshot.eps > 0:
        result["pe"] = round(price_in_reporting / snapshot.eps, 2)
    if snapshot.book_value_per_share and snapshot.book_value_per_share > 0:
        result["pbv"] = round(price_in_reporting / snapshot.book_value_per_share, 2)

    if result["pe"] is None and result["pbv"] is None:
        result["note"] = "งบไม่มี EPS หรือส่วนของผู้ถือหุ้นที่ใช้คำนวณมูลค่าได้"
        return result

    result["verified"] = True
    if result["pe"] is None:
        result["note"] = "บริษัทขาดทุนหรือไม่มี EPS จึงใช้ได้เฉพาะ P/BV"
    elif result["fx_adjusted"]:
        result["note"] = (
            f"แปลงราคาจาก {trading} เป็น {reporting} ก่อนคำนวณ เพราะงบรายงานคนละสกุลกับราคาซื้อขาย"
        )
    else:
        result["note"] = f"คำนวณจากงบและราคาสกุล {currency_label(reporting)}"
    return result
