"""ทำความรู้จักหุ้นรายตัวตามกรอบ ONE Investor.

ลำดับการอ่านเหมือนในหลักสูตร: รู้ว่าเป็นหุ้นประเภทไหน -> ผ่าน Financial Quality
Filter 4 ด่านหรือไม่ -> ราคามี Margin of Safety พอไหม -> จึงค่อยตัดสินใจ

ทุกตัวเลขในหน้านี้คำนวณจากงบการเงินที่ยืนยันแล้วและราคาจริงเท่านั้น หัวข้อที่
ข้อมูลสาธารณะไม่ครอบคลุม เช่น สัดส่วนการถือหุ้นของผู้บริหาร จะถูกทำเครื่องหมายว่า
ต้องตรวจเอง ไม่มีการเติมค่าประมาณลงไปแทน
"""

from __future__ import annotations

from datetime import date
from statistics import mean, median, pstdev
from typing import Any

from .currency import convert, currency_label, price_scale, trading_currency
from .models import StockCandle


# เกณฑ์ตามหลักสูตร ONE Investor
ROE_TARGET = 15.0
ROIC_TARGET = 10.0
DEBT_TO_EQUITY_TARGET = 1.5
MARGIN_OF_SAFETY_TARGET = 20.0
DILUTION_TOLERANCE_PCT = 5.0
GROWTH_YEARS_REQUIRED = 3
PEG_MINIMUM_GROWTH = 10.0
# เมื่อวิธีประเมินมูลค่าให้ผลห่างกันเกินเท่านี้ ตัวเลขกลางไม่มีความหมายพอจะใช้ตัดสินใจ
VALUATION_SPREAD_LIMIT = 1.8


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _cagr(last: float | None, first: float | None, years: int) -> float | None:
    if last is None or first is None or first <= 0 or last <= 0 or years <= 0:
        return None
    return ((last / first) ** (1 / years) - 1) * 100


def _growth_years(values: list[float | None]) -> int:
    """จำนวนปีติดต่อกันล่าสุดที่ค่าเพิ่มขึ้นจากปีก่อนหน้า"""
    streak = 0
    for index in range(len(values) - 1, 0, -1):
        current, previous = values[index], values[index - 1]
        if current is None or previous is None or current <= previous:
            break
        streak += 1
    return streak


def _series(annual: list[dict[str, Any]], metric: str) -> list[float | None]:
    return [_number((period.get("metrics") or {}).get(metric)) for period in annual]


def _ratio_series(annual: list[dict[str, Any]], key: str) -> list[float | None]:
    return [_number((period.get("ratios") or {}).get(key)) for period in annual]


def _roic_series(annual: list[dict[str, Any]]) -> list[float | None]:
    """NOPAT หารด้วยเงินลงทุนรวม (หนี้ที่มีภาระดอกเบี้ย + ส่วนของผู้ถือหุ้น)"""
    output: list[float | None] = []
    for period in annual:
        metrics = period.get("metrics") or {}
        operating = _number(metrics.get("operating_income"))
        pretax = _number(metrics.get("pretax_income"))
        tax = _number(metrics.get("tax_provision"))
        debt = _number(metrics.get("total_debt")) or 0.0
        equity = _number(metrics.get("stockholders_equity"))
        invested = debt + (equity or 0.0)
        if operating is None or not invested:
            output.append(None)
            continue
        tax_rate = tax / pretax if pretax and tax is not None and pretax > 0 else 0.20
        tax_rate = min(max(tax_rate, 0.0), 0.45)
        output.append(operating * (1 - tax_rate) / invested * 100)
    return output


def _shares_series(annual: list[dict[str, Any]]) -> list[float | None]:
    """จำนวนหุ้นถอดจากกำไรสุทธิหารกำไรต่อหุ้นของงวดเดียวกัน"""
    output: list[float | None] = []
    for period in annual:
        metrics = period.get("metrics") or {}
        eps = _number(metrics.get("basic_eps"))
        net_income = _number(metrics.get("net_income"))
        if not eps or net_income is None or eps == 0:
            output.append(None)
            continue
        shares = net_income / eps
        output.append(shares if shares > 0 else None)
    return output


def _close_on_or_before(candles: list[StockCandle], target: date) -> float | None:
    chosen = None
    for candle in candles:
        if candle.date <= target:
            chosen = candle.close
        else:
            break
    return chosen


def _historical_pe(
    annual: list[dict[str, Any]],
    candles: list[StockCandle],
    trading: str,
    reporting: str,
    rates: dict[str, float] | None,
    symbol: str,
) -> list[dict[str, Any]]:
    """P/E ณ วันสิ้นงวดของแต่ละปี ใช้ราคาจริงในวันนั้นเทียบ EPS ของงวดนั้น"""
    scale = price_scale(symbol)
    output: list[dict[str, Any]] = []
    for period in annual:
        eps = _number((period.get("metrics") or {}).get("basic_eps"))
        try:
            period_end = date.fromisoformat(str(period.get("period_end"))[:10])
        except ValueError:
            continue
        price = _close_on_or_before(candles, period_end)
        if not eps or eps <= 0 or price is None:
            continue
        price_in_reporting = (
            price * scale
            if trading == reporting
            else convert(price * scale, trading, reporting, rates)
        )
        if price_in_reporting is None:
            continue
        output.append(
            {
                "year": str(period.get("period_end"))[:4],
                "price": round(price, 4),
                "eps": round(eps, 4),
                "pe": round(price_in_reporting / eps, 2),
            }
        )
    return output


def _trend_cagr(values: list[float | None], label_unit: str = "") -> dict[str, Any]:
    """อัตราเติบโตเฉลี่ยต่อปีของรายการที่เป็นจำนวนเงิน

    ใช้ปีแรกและปีล่าสุดที่มีข้อมูลจริง ถ้าช่วงนั้นมีปีที่ติดลบ การคิดเป็นอัตรา
    ทบต้นจะให้ตัวเลขที่ไม่มีความหมาย จึงบอกทิศทางเป็นคำแทน
    """
    known = [value for value in values if value is not None]
    if len(known) < 2:
        return {"kind": "none", "label": "ข้อมูลไม่พอเทียบ", "value": None, "tone": "unknown", "years": 0}
    first, last = known[0], known[-1]
    span = len(known) - 1
    if first <= 0 and last > 0:
        return {"kind": "turn", "label": f"พลิกจากติดลบเป็นบวกใน {span} ปี", "value": None, "tone": "ok", "years": span}
    if first > 0 and last <= 0:
        return {"kind": "turn", "label": f"พลิกจากบวกเป็นติดลบใน {span} ปี", "value": None, "tone": "bad", "years": span}
    if first <= 0 or last <= 0:
        return {"kind": "none", "label": "ติดลบตลอดช่วง เทียบอัตราเติบโตไม่ได้", "value": None, "tone": "bad", "years": span}

    cagr = ((last / first) ** (1 / span) - 1) * 100
    if cagr >= 0.5:
        word, tone = "โตเฉลี่ย", "ok"
    elif cagr <= -0.5:
        word, tone = "แย่ลงเฉลี่ย", "bad"
    else:
        word, tone = "แทบไม่เปลี่ยน", "warn"
    suffix = f" {label_unit}" if label_unit else ""
    label = (
        f"{word} {cagr:+.1f}% ต่อปี (เทียบ {span} ปี){suffix}"
        if word != "แทบไม่เปลี่ยน"
        else f"{word} ({cagr:+.1f}% ต่อปี เทียบ {span} ปี){suffix}"
    )
    return {"kind": "cagr", "label": label, "value": round(cagr, 2), "tone": tone, "years": span}


def _trend_change(
    values: list[float | None],
    unit: str = "จุด",
    higher_is_better: bool = True,
) -> dict[str, Any]:
    """การเปลี่ยนแปลงของอัตราส่วน วัดเป็นส่วนต่าง ไม่ใช่อัตราทบต้น

    ROE ที่ขยับจาก 10% เป็น 15% เพิ่มขึ้น 5 จุด การรายงานว่าโต 50% ต่อปี
    จะทำให้เข้าใจผิดว่าเป็นการเติบโตแบบทบต้น
    """
    known = [value for value in values if value is not None]
    if len(known) < 2:
        return {"kind": "none", "label": "ข้อมูลไม่พอเทียบ", "value": None, "tone": "unknown", "years": 0}
    span = len(known) - 1
    latest = known[-1]
    change = latest - known[0]
    latest_text = f"{latest:,.1f}{'%' if unit == 'จุด' else ' เท่า'}"
    threshold = 0.5 if unit == "จุด" else 0.05
    if abs(change) < threshold:
        return {
            "kind": "flat",
            "label": f"ล่าสุด {latest_text} · ทรงตัว ({change:+.2f} {unit} ใน {span} ปี)",
            "value": round(change, 2),
            "tone": "warn",
            "years": span,
        }
    # แยกทิศทางของตัวเลขออกจากคำตัดสิน เพราะหนี้ที่ลดลงคือเรื่องดี
    direction = "เพิ่มขึ้น" if change > 0 else "ลดลง"
    improving = change > 0 if higher_is_better else change < 0
    verdict = "ดีขึ้น" if improving else "แย่ลง"
    return {
        "kind": "change",
        "label": f"ล่าสุด {latest_text} · {direction} {abs(change):,.1f} {unit} ใน {span} ปี ({verdict})",
        "value": round(change, 2),
        "tone": "ok" if improving else "bad",
        "years": span,
    }


def _series_summary(annual: list[dict[str, Any]], reporting: str) -> list[dict[str, Any]]:
    """ตารางตัวเลขหลักย้อนหลัง พร้อมสรุปทิศทางของแต่ละแถวเป็นตัวเลขเดียว"""
    revenue = _series(annual, "total_revenue")
    net_income = _series(annual, "net_income")
    eps = _series(annual, "basic_eps")
    cash_flow = _series(annual, "operating_cash_flow")
    roe = _ratio_series(annual, "roe")
    gross_margin = _ratio_series(annual, "gross_margin")
    net_margin = _ratio_series(annual, "net_margin")
    debt_to_equity = _ratio_series(annual, "debt_to_equity")

    return [
        {
            "key": "revenue",
            "label": "รายได้รวม",
            "unit": f"ล้าน {reporting}",
            "format": "millions",
            "values": revenue,
            "trend": _trend_cagr(revenue),
        },
        {
            "key": "net_income",
            "label": "กำไรสุทธิ",
            "unit": f"ล้าน {reporting}",
            "format": "millions",
            "values": net_income,
            "trend": _trend_cagr(net_income),
        },
        {
            "key": "eps",
            "label": "กำไรต่อหุ้น (EPS)",
            "unit": f"{reporting} ต่อหุ้น",
            "format": "decimal",
            "values": eps,
            "trend": _trend_cagr(eps),
        },
        {
            "key": "operating_cash_flow",
            "label": "กระแสเงินสดจากการดำเนินงาน",
            "unit": f"ล้าน {reporting}",
            "format": "millions",
            "values": cash_flow,
            "trend": _trend_cagr(cash_flow),
        },
        {
            "key": "roe",
            "label": "ROE - ผลตอบแทนผู้ถือหุ้น",
            "unit": "%",
            "format": "percent",
            "values": roe,
            "trend": _trend_change(roe, "จุด", higher_is_better=True),
        },
        {
            "key": "gross_margin",
            "label": "อัตรากำไรขั้นต้น",
            "unit": "%",
            "format": "percent",
            "values": gross_margin,
            "trend": _trend_change(gross_margin, "จุด", higher_is_better=True),
        },
        {
            "key": "net_margin",
            "label": "อัตรากำไรสุทธิ",
            "unit": "%",
            "format": "percent",
            "values": net_margin,
            "trend": _trend_change(net_margin, "จุด", higher_is_better=True),
        },
        {
            "key": "debt_to_equity",
            "label": "หนี้สินต่อทุน (D/E)",
            "unit": "เท่า",
            "format": "multiple",
            "values": debt_to_equity,
            "trend": _trend_change(debt_to_equity, "เท่า", higher_is_better=False),
        },
    ]


def _lynch_type(
    revenue_cagr: float | None,
    profit_cagr: float | None,
    roe_latest: float | None,
    pbv: float | None,
    profit_growth_volatility: float | None,
    turned_profitable: bool,
    dividend_years: int,
) -> dict[str, Any]:
    """จำแนกหุ้น 6 ประเภทตาม Peter Lynch จากตัวเลขที่วัดได้จริง"""
    reasons: list[str] = []
    growth = revenue_cagr if revenue_cagr is not None else profit_cagr

    if turned_profitable:
        reasons.append("บริษัทเคยขาดทุนแล้วกลับมามีกำไรในช่วงที่ดูงบ")
        return {
            "key": "turnaround",
            "label": "Turnarounds - หุ้นฟื้นตัว",
            "description": "บริษัทเคยมีปัญหาแล้วกำลังกลับมา ผลตอบแทนอาจสูงแต่ต้องตรวจว่าการฟื้นตัวยั่งยืนจริง",
            "watch": "ตรวจว่ากำไรที่กลับมาเป็นของธุรกิจหลัก ไม่ใช่รายการพิเศษครั้งเดียว",
            "reasons": reasons,
        }

    if pbv is not None and pbv < 1.0 and (roe_latest is None or roe_latest < 8):
        reasons.append(f"P/BV เพียง {pbv:.2f} เท่า ขณะที่ผลตอบแทนผู้ถือหุ้นยังต่ำ")
        return {
            "key": "asset_play",
            "label": "Asset Plays - หุ้นมูลค่าที่ซ่อนอยู่",
            "description": "ราคาต่ำกว่ามูลค่าสินทรัพย์ในบัญชี ต้องหาให้เจอว่าสินทรัพย์นั้นมีมูลค่าจริงหรือไม่",
            "watch": "ตรวจว่าสินทรัพย์ตีราคาไว้สมจริง และมีตัวกระตุ้นให้ตลาดรับรู้มูลค่านั้น",
            "reasons": reasons,
        }

    if profit_growth_volatility is not None and profit_growth_volatility > 45:
        reasons.append(f"การเติบโตของกำไรเหวี่ยงมาก (ส่วนเบี่ยงเบน {profit_growth_volatility:.0f} จุด)")
        return {
            "key": "cyclical",
            "label": "Cyclical - หุ้นวัฏจักร",
            "description": "ผลประกอบการขึ้นลงตามรอบเศรษฐกิจ ซื้อตอนกำไรแย่และขายตอนกำไรดีคือจังหวะที่ถูก",
            "watch": "อย่าดู P/E ต่ำแล้วคิดว่าถูก หุ้นวัฏจักร P/E ต่ำที่สุดมักคือจุดที่ใกล้จบรอบ",
            "reasons": reasons,
        }

    if growth is not None and growth >= 20:
        reasons.append(f"รายได้เติบโตเฉลี่ย {growth:.1f}% ต่อปี")
        return {
            "key": "fast_grower",
            "label": "Fast Growers - หุ้นเติบโตเร็ว",
            "description": "โตเร็วและยังมีช่องขยายตัว เป็นกลุ่มที่ให้ผลตอบแทนสูงที่สุดถ้าเลือกถูกตัว",
            "watch": "ตรวจว่าการเติบโตยังมีที่ไป และงบดุลรับการขยายตัวไหว",
            "reasons": reasons,
        }

    if growth is not None and growth >= 8:
        reasons.append(f"รายได้เติบโตเฉลี่ย {growth:.1f}% ต่อปีอย่างสม่ำเสมอ")
        if roe_latest is not None and roe_latest >= ROE_TARGET:
            reasons.append(f"ผลตอบแทนผู้ถือหุ้น {roe_latest:.1f}% อยู่ในระดับดี")
        return {
            "key": "stalwart",
            "label": "Stalwarts - หุ้นคุณภาพดี เติบโตต่อเนื่อง",
            "description": "บริษัทใหญ่ที่มั่นคง โตสม่ำเสมอ เหมาะถือยาวและรับการเติบโตของธุรกิจ",
            "watch": "ผลตอบแทนมาจากการถือยาว ไม่ใช่การเก็งกำไรระยะสั้น",
            "reasons": reasons,
        }

    if growth is not None:
        reasons.append(f"รายได้เติบโตเฉลี่ยเพียง {growth:.1f}% ต่อปี")
    if dividend_years:
        reasons.append("มีกระแสเงินสดพอจ่ายผลตอบแทนคืนผู้ถือหุ้น")
    return {
        "key": "slow_grower",
        "label": "Slow Growers - หุ้นเติบโตช้าแต่มั่นคง",
        "description": "ธุรกิจอิ่มตัว โตช้า ผลตอบแทนหลักมาจากเงินปันผลมากกว่าราคา",
        "watch": "ถ้าไม่จ่ายปันผลและโตช้า ต้องถามว่าถือไว้เพื่ออะไร",
        "reasons": reasons,
    }


MEGATREND_BY_SECTOR: dict[str, tuple[str, str]] = {
    "semiconductors": ("Semiconductor และ AI", "ชิปคือน้ำมันใหม่ของโลกดิจิทัล ความต้องการมาจาก AI, Cloud, EV และ IoT"),
    "software": ("AI และ Cloud", "องค์กรทั่วโลกย้ายขึ้น Cloud และเริ่มฝัง AI ในทุกกระบวนการทำงาน"),
    "technology": ("AI และ Cloud", "เทคโนโลยีเป็นฐานของเมกะเทรนด์อื่นเกือบทั้งหมด"),
    "information technology": ("AI และ Cloud", "เทคโนโลยีเป็นฐานของเมกะเทรนด์อื่นเกือบทั้งหมด"),
    "health care": ("Healthcare และ Aging Society", "สังคมผู้สูงอายุทำให้ความต้องการการรักษาและยาเพิ่มขึ้นไม่หยุด"),
    "healthcare": ("Healthcare และ Aging Society", "สังคมผู้สูงอายุทำให้ความต้องการการรักษาและยาเพิ่มขึ้นไม่หยุด"),
    "pharmaceuticals": ("Healthcare", "เทคโนโลยีการแพทย์ก้าวหน้าและตลาดโตต่อเนื่อง"),
    "utilities": ("Clean Energy", "การเปลี่ยนผ่านสู่พลังงานสะอาดต้องลงทุนโครงสร้างพื้นฐานมหาศาล"),
    "energy": ("การเปลี่ยนผ่านพลังงาน", "อยู่ในช่วงเปลี่ยนผ่าน เป็นได้ทั้งโอกาสและความเสี่ยงเชิงโครงสร้าง"),
    "automobiles": ("EV และ Future Mobility", "อุตสาหกรรมยานยนต์กำลังเปลี่ยนฐานเทคโนโลยีทั้งระบบ"),
    "digital infrastructure": ("Cloud และ Big Data", "ปริมาณข้อมูลโตเร็วกว่าโครงสร้างพื้นฐานที่มีอยู่"),
    "financials": ("Digital Finance", "บริการการเงินย้ายสู่ดิจิทัล แต่ยังผูกกับวัฏจักรดอกเบี้ย"),
    "banking": ("Digital Finance", "บริการการเงินย้ายสู่ดิจิทัล แต่ยังผูกกับวัฏจักรดอกเบี้ย"),
}


def _megatrend(sector: str) -> dict[str, Any]:
    key = (sector or "").strip().lower()
    for name, (label, note) in MEGATREND_BY_SECTOR.items():
        if name in key:
            return {"matched": True, "label": label, "note": note}
    return {
        "matched": False,
        "label": "ยังไม่จับคู่กับเมกะเทรนด์",
        "note": "อุตสาหกรรมนี้ไม่ได้อยู่ในรายการเมกะเทรนด์ที่ระบบจับคู่ไว้ ต้องประเมินแนวโน้มระยะยาวเอง",
    }


def _criterion(
    label: str,
    passed: bool | None,
    value_text: str,
    target_text: str,
    note: str = "",
) -> dict[str, Any]:
    return {
        "label": label,
        "passed": passed,
        "value": value_text,
        "target": target_text,
        "note": note,
        "state": "unknown" if passed is None else ("pass" if passed else "fail"),
    }


def _stage_growth(annual: list[dict[str, Any]], years: int) -> dict[str, Any]:
    revenue = _series(annual, "total_revenue")
    eps = _series(annual, "basic_eps")
    profit = _series(annual, "net_income")
    revenue_cagr = _cagr(revenue[-1], revenue[0], years)
    eps_cagr = _cagr(eps[-1], eps[0], years)
    profit_cagr = _cagr(profit[-1], profit[0], years)
    criteria = [
        _criterion(
            "Revenue - รายได้เติบโตต่อเนื่อง",
            _growth_years(revenue) >= GROWTH_YEARS_REQUIRED,
            f"โตติดต่อกัน {_growth_years(revenue)} ปี"
            + (f" · CAGR {revenue_cagr:.1f}%" if revenue_cagr is not None else ""),
            f"เติบโตต่อเนื่องอย่างน้อย {GROWTH_YEARS_REQUIRED} ปี",
            "รายได้คือจุดเริ่มต้นของทุกอย่าง ถ้ารายได้ไม่โต กำไรที่โตมักมาจากการลดต้นทุนซึ่งทำได้จำกัด",
        ),
        _criterion(
            "EPS - กำไรต่อหุ้นเติบโต",
            _growth_years(eps) >= GROWTH_YEARS_REQUIRED,
            f"โตติดต่อกัน {_growth_years(eps)} ปี"
            + (f" · CAGR {eps_cagr:.1f}%" if eps_cagr is not None else ""),
            f"เติบโตต่อเนื่องอย่างน้อย {GROWTH_YEARS_REQUIRED} ปี",
            "EPS โตแปลว่าผู้ถือหุ้นเดิมได้ประโยชน์จริง ไม่ถูกเจือจางจากการเพิ่มทุน",
        ),
        _criterion(
            "Profit - กำไรสุทธิเติบโต",
            _growth_years(profit) >= GROWTH_YEARS_REQUIRED,
            f"โตติดต่อกัน {_growth_years(profit)} ปี"
            + (f" · CAGR {profit_cagr:.1f}%" if profit_cagr is not None else ""),
            f"เติบโตต่อเนื่องอย่างน้อย {GROWTH_YEARS_REQUIRED} ปี",
            "กำไรต้องโตพร้อมรายได้ จึงจะเรียกว่าธุรกิจขยายตัวอย่างมีคุณภาพ",
        ),
    ]
    return {
        "key": "growth",
        "number": 1,
        "title": "GROWTH",
        "subtitle": "ธุรกิจเติบโตอย่างต่อเนื่อง",
        "goal": "หาบริษัทที่กำลังเติบโต ไม่ใช่บริษัทที่เคยเติบโต",
        "criteria": criteria,
        "passed": all(item["passed"] for item in criteria),
        "metrics": {"revenue_cagr": revenue_cagr, "eps_cagr": eps_cagr, "profit_cagr": profit_cagr},
    }


def _stage_quality(annual: list[dict[str, Any]]) -> dict[str, Any]:
    roe = _ratio_series(annual, "roe")
    roic = _roic_series(annual)
    cash_flow = _series(annual, "operating_cash_flow")
    debt_to_equity = _ratio_series(annual, "debt_to_equity")
    roe_latest = roe[-1] if roe else None
    roic_latest = roic[-1] if roic else None
    positive_cash_years = sum(1 for value in cash_flow if value is not None and value > 0)
    known_cash_years = sum(1 for value in cash_flow if value is not None)
    de_latest = debt_to_equity[-1] if debt_to_equity else None

    # ทุนติดลบทำให้ ROE และ D/E ไม่มีความหมาย ต้องบอกเหตุผลแทนการขึ้นว่าไม่มีข้อมูลเฉย ๆ
    latest_period = annual[-1] if annual else {}
    negative_equity = bool(latest_period.get("negative_equity"))
    ratio_notes = latest_period.get("ratio_notes") or {}
    equity_warning = "ส่วนของผู้ถือหุ้นติดลบ ธุรกิจนี้มีหนี้สินมากกว่าสินทรัพย์ตามบัญชี"

    criteria = [
        _criterion(
            "ROE - ผลตอบแทนต่อส่วนของผู้ถือหุ้น",
            False if negative_equity else (None if roe_latest is None else roe_latest >= ROE_TARGET),
            ratio_notes.get("roe") or ("ไม่มีข้อมูล" if roe_latest is None else f"{roe_latest:.1f}%"),
            f"มากกว่า {ROE_TARGET:.0f}% ขึ้นไป",
            equity_warning if negative_equity else "วัดว่าบริษัทเอาเงินของผู้ถือหุ้นไปสร้างผลตอบแทนได้เก่งแค่ไหน",
        ),
        _criterion(
            "ROIC - ผลตอบแทนต่อเงินลงทุนรวม",
            None if roic_latest is None else roic_latest >= ROIC_TARGET,
            "ไม่มีข้อมูล" if roic_latest is None else f"{roic_latest:.1f}%",
            f"มากกว่า {ROIC_TARGET:.0f}% และควรสูงกว่าต้นทุนเงินทุน",
            "ต่างจาก ROE ตรงที่รวมหนี้เข้าไปด้วย บริษัทที่กู้มาเยอะจะซ่อนความจริงไว้ใน ROE ไม่ได้",
        ),
        _criterion(
            "Cash Flow - กระแสเงินสดจากการดำเนินงาน",
            None if not known_cash_years else positive_cash_years == known_cash_years,
            "ไม่มีข้อมูล" if not known_cash_years else f"เป็นบวก {positive_cash_years}/{known_cash_years} ปี",
            "เป็นบวกทุกปีและสม่ำเสมอ",
            "กำไรทางบัญชีตกแต่งได้ แต่เงินสดที่ไหลเข้าจริงตกแต่งยากกว่ามาก",
        ),
        _criterion(
            "Debt to Equity - หนี้สินต่อทุน",
            False if negative_equity else (None if de_latest is None else de_latest <= DEBT_TO_EQUITY_TARGET),
            ratio_notes.get("debt_to_equity") or ("ไม่มีข้อมูล" if de_latest is None else f"{de_latest:.2f} เท่า"),
            f"ไม่เกิน {DEBT_TO_EQUITY_TARGET:.1f} เท่า",
            equity_warning if negative_equity else "หนี้น้อยแปลว่าบริษัทยืนหยัดผ่านช่วงเศรษฐกิจแย่ได้โดยไม่ต้องเพิ่มทุน",
        ),
    ]
    return {
        "key": "quality",
        "number": 2,
        "title": "QUALITY",
        "subtitle": "คุณภาพและความแข็งแกร่งของธุรกิจ",
        "goal": "ธุรกิจที่เติบโตได้ดี ต้องมีคุณภาพที่แข็งแกร่งและยืนหยัดได้ในทุกสภาวะ",
        "criteria": criteria,
        "passed": all(item["passed"] for item in criteria),
        "metrics": {"roe": roe_latest, "roic": roic_latest, "debt_to_equity": de_latest},
        "negative_equity": negative_equity,
    }


def _stage_efficiency(annual: list[dict[str, Any]]) -> dict[str, Any]:
    gross = _ratio_series(annual, "gross_margin")
    net = _ratio_series(annual, "net_margin")
    operating: list[float | None] = []
    for period in annual:
        metrics = period.get("metrics") or {}
        operating_income = _number(metrics.get("operating_income"))
        revenue = _number(metrics.get("total_revenue"))
        operating.append(operating_income / revenue * 100 if operating_income is not None and revenue else None)

    def _holding_or_improving(values: list[float | None], label: str, note: str) -> dict[str, Any]:
        known = [value for value in values if value is not None]
        if len(known) < 2:
            return _criterion(label, None, "ข้อมูลไม่พอเทียบแนวโน้ม", "คงที่หรือดีขึ้น 3-5 ปี", note)
        # เทียบครึ่งหลังกับครึ่งแรก เพื่อไม่ให้ปีเดียวที่แกว่งตัดสินแนวโน้มทั้งหมด
        half = max(1, len(known) // 2)
        early, late = mean(known[:half]), mean(known[-half:])
        improving = late >= early - 1.0
        return _criterion(
            label,
            improving,
            f"{known[-1]:.1f}% (เฉลี่ยช่วงหลัง {late:.1f}% เทียบช่วงแรก {early:.1f}%)",
            "คงที่หรือดีขึ้น 3-5 ปี",
            note,
        )

    criteria = [
        _holding_or_improving(gross, "Gross Margin - อัตรากำไรขั้นต้น", "สะท้อนอำนาจตั้งราคาและการคุมต้นทุนการผลิต ถ้าลดลงเรื่อย ๆ แปลว่ากำลังโดนแข่งขันกดดัน"),
        _holding_or_improving(operating, "Operating Margin - อัตรากำไรจากการดำเนินงาน", "สะท้อนประสิทธิภาพการบริหารค่าใช้จ่าย เป็นตัวที่ผู้บริหารควบคุมได้มากที่สุด"),
        _holding_or_improving(net, "Net Margin - อัตรากำไรสุทธิ", "เหลือเท่าไรจริง ๆ หลังหักทุกอย่าง มาร์จิ้นสูงและยั่งยืนมักแปลว่ามีความได้เปรียบในการแข่งขัน"),
    ]
    return {
        "key": "efficiency",
        "number": 3,
        "title": "EFFICIENCY",
        "subtitle": "ประสิทธิภาพในการดำเนินงาน",
        "goal": "ทำธุรกิจให้คุ้มค่า คุมต้นทุนเก่ง แปลงรายได้เป็นกำไรได้ดี",
        "criteria": criteria,
        "passed": all(item["passed"] for item in criteria),
        "metrics": {
            "gross_margin": gross[-1] if gross else None,
            "operating_margin": operating[-1] if operating else None,
            "net_margin": net[-1] if net else None,
        },
    }


def _stage_management(annual: list[dict[str, Any]], years: int) -> dict[str, Any]:
    shares = _shares_series(annual)
    known = [value for value in shares if value is not None]
    dilution_cagr = _cagr(known[-1], known[0], years) if len(known) >= 2 else None
    eps_cagr = _cagr(_series(annual, "basic_eps")[-1], _series(annual, "basic_eps")[0], years)

    if dilution_cagr is None:
        dilution_criterion = _criterion(
            "Dilution - การเพิ่มจำนวนหุ้น",
            None,
            "ถอดจำนวนหุ้นจากงบไม่ได้",
            f"จำนวนหุ้นเพิ่มไม่เกิน {DILUTION_TOLERANCE_PCT:.0f}% ต่อปี",
            "ถ้าจำนวนหุ้นเพิ่มเร็วกว่ากำไร มูลค่าต่อหุ้นของเราจะถูกเจือจางลงแม้บริษัทจะโต",
        )
    else:
        detail = f"จำนวนหุ้นเปลี่ยน {dilution_cagr:+.1f}% ต่อปี"
        if eps_cagr is not None:
            detail += f" · EPS โต {eps_cagr:+.1f}% ต่อปี"
        dilution_criterion = _criterion(
            "Dilution - การเพิ่มจำนวนหุ้น",
            dilution_cagr <= DILUTION_TOLERANCE_PCT,
            detail,
            f"จำนวนหุ้นเพิ่มไม่เกิน {DILUTION_TOLERANCE_PCT:.0f}% ต่อปี",
            "ถ้าจำนวนหุ้นเพิ่มเร็วกว่ากำไร มูลค่าต่อหุ้นของเราจะถูกเจือจางลงแม้บริษัทจะโต",
        )

    criteria = [
        _criterion(
            "Insider Alignment - ผู้บริหารถือหุ้นไปกับเราไหม",
            None,
            "ข้อมูลสาธารณะที่ระบบใช้ไม่ครอบคลุมสัดส่วนการถือหุ้นของผู้บริหาร",
            "ผู้บริหารและกรรมการถือหุ้นมากกว่า 5% และไม่ทยอยขายออก",
            "ต้องเปิดดูเองจากแบบ 56-1 One Report สำหรับหุ้นไทย หรือ SEC Form 4 และ DEF 14A สำหรับหุ้นสหรัฐ",
        ),
        dilution_criterion,
    ]
    known_criteria = [item for item in criteria if item["passed"] is not None]
    return {
        "key": "management",
        "number": 4,
        "title": "MANAGEMENT",
        "subtitle": "ผู้บริหารและการจัดการที่เชื่อถือได้",
        "goal": "เลือกหุ้นที่ผู้บริหารไว้ใจได้ บริหารธุรกิจอย่างมีธรรมาภิบาล",
        "criteria": criteria,
        "passed": bool(known_criteria) and all(item["passed"] for item in known_criteria),
        "needs_manual_check": True,
        "metrics": {"share_count_cagr": dilution_cagr, "eps_cagr": eps_cagr},
    }


def _valuation_methods(
    annual: list[dict[str, Any]],
    history: list[dict[str, Any]],
    eps_latest: float | None,
    eps_cagr: float | None,
    analyst_fair_value_reporting: float | None,
) -> list[dict[str, Any]]:
    """สามวิธีประเมินมูลค่าตามหลักสูตร ทุกวิธีบอกที่มาของตัวเลขไว้ในตัวเอง"""
    methods: list[dict[str, Any]] = []

    pe_values = [row["pe"] for row in history if row.get("pe")]
    if pe_values and eps_latest and eps_latest > 0:
        average_pe = mean(pe_values)
        methods.append(
            {
                "key": "historical_pe",
                "name": "P/E เฉลี่ยย้อนหลัง",
                "fair_value": round(average_pe * eps_latest, 4),
                "detail": f"P/E เฉลี่ย {average_pe:.1f} เท่าจาก {len(pe_values)} ปี คูณ EPS ล่าสุด {eps_latest:.2f}",
                "note": "ตั้งอยู่บนสมมติฐานว่าตลาดจะให้ราคาหุ้นตัวนี้เหมือนที่เคยให้มา",
            }
        )

    if eps_latest and eps_latest > 0 and eps_cagr is not None and eps_cagr >= PEG_MINIMUM_GROWTH:
        fair_pe = min(eps_cagr, 40.0)
        methods.append(
            {
                "key": "peg",
                "name": "PEG เท่ากับ 1",
                "fair_value": round(fair_pe * eps_latest, 4),
                "detail": f"ให้ P/E เท่ากับอัตราการเติบโตของ EPS ที่ {fair_pe:.1f}% คูณ EPS ล่าสุด {eps_latest:.2f}",
                "note": "วิธีของ Peter Lynch ใช้ได้ดีกับหุ้นเติบโต แต่ไม่เหมาะกับหุ้นวัฏจักรและหุ้นฟื้นตัว",
            }
        )
    elif eps_latest and eps_latest > 0:
        methods.append(
            {
                "key": "peg",
                "name": "PEG เท่ากับ 1",
                "fair_value": None,
                "skipped": True,
                "detail": (
                    f"ไม่ใช้วิธีนี้เพราะ EPS โตเฉลี่ยเพียง {eps_cagr:.1f}% ต่อปี"
                    if eps_cagr is not None
                    else "ไม่ใช้วิธีนี้เพราะคำนวณอัตราการเติบโตของ EPS ไม่ได้"
                ),
                "note": f"PEG ออกแบบมาสำหรับหุ้นเติบโต จึงใช้เมื่อ EPS โตอย่างน้อย {PEG_MINIMUM_GROWTH:.0f}% ต่อปีเท่านั้น",
            }
        )

    book_values = [
        _number((period.get("metrics") or {}).get("stockholders_equity")) for period in annual
    ]
    shares = _shares_series(annual)
    if book_values and shares and book_values[-1] and shares[-1]:
        book_per_share = book_values[-1] / shares[-1]
        methods.append(
            {
                "key": "book_value",
                "name": "มูลค่าทางบัญชีต่อหุ้น",
                "fair_value": round(book_per_share, 4),
                "detail": f"ส่วนของผู้ถือหุ้นหารด้วยจำนวนหุ้น ได้ {book_per_share:.2f} ต่อหุ้น",
                "note": "เป็นพื้นราคาขั้นต่ำ ไม่ใช่มูลค่าที่เหมาะสม ใช้เตือนว่าราคาลงได้ลึกแค่ไหนก่อนถึงมูลค่าสินทรัพย์",
                "is_floor": True,
            }
        )

    if analyst_fair_value_reporting:
        methods.append(
            {
                "key": "analyst",
                "name": "มูลค่าที่นักวิเคราะห์บันทึกไว้",
                "fair_value": round(analyst_fair_value_reporting, 4),
                "detail": "ค่าที่บันทึกเองในบันทึกงานวิจัยของหุ้นตัวนี้",
                "note": "เป็นดุลพินิจของคนบันทึก ไม่ใช่ตัวเลขที่ระบบคำนวณ",
            }
        )

    return methods


def build_stock_profile(
    symbol: str,
    financials: dict[str, Any] | None,
    candles: list[StockCandle],
    snapshot: Any,
    research: dict[str, Any] | None = None,
    rates: dict[str, float] | None = None,
) -> dict[str, Any]:
    """ประกอบหน้าทำความรู้จักหุ้นตามลำดับ ธุรกิจ -> คุณภาพ -> ราคา -> ตัดสินใจ"""
    research = research or {}
    market = getattr(snapshot, "market", "") or ""
    sector = getattr(snapshot, "sector", "") or ""
    trading = trading_currency(symbol, market)
    last_price = candles[-1].close if candles else 0.0
    price_as_of = candles[-1].date.isoformat() if candles else ""

    profile: dict[str, Any] = {
        "symbol": symbol,
        "name": getattr(snapshot, "name", symbol),
        "market": market,
        "sector": sector,
        "trading_currency": trading,
        "trading_currency_label": currency_label(trading),
        "last_price": round(last_price, 4),
        "price_as_of": price_as_of,
        "megatrend": _megatrend(sector),
        "qualitative": {
            "moat": research.get("moat") or "",
            "ai_trend": research.get("ai_trend") or "",
            "thesis": research.get("thesis") or "",
            "status": research.get("status") or "Watch",
            "note": research.get("note") or "",
            "recorded": bool(research.get("research_verified")),
        },
        "five_forces": FIVE_FORCES,
        "flow": FINANCIAL_QUALITY_FLOW,
    }

    annual = (financials or {}).get("annual") or []
    if len(annual) < 2:
        profile.update(
            {
                "available": False,
                "reason": "ยังไม่มีงบการเงินย้อนหลังพอสำหรับประเมินหุ้นตัวนี้ กดดึงงบในแท็บงบการเงินก่อน",
                "reporting_currency": "",
                "stages": [],
                "valuation": {"available": False},
            }
        )
        return profile

    reporting = str((financials or {}).get("currency") or "").upper()
    years = max(1, len(annual) - 1)
    eps_series = _series(annual, "basic_eps")
    profit_series = _series(annual, "net_income")
    revenue_series = _series(annual, "total_revenue")
    roe_series = _ratio_series(annual, "roe")

    profit_growths = [
        (profit_series[index] / profit_series[index - 1] - 1) * 100
        for index in range(1, len(profit_series))
        if profit_series[index] is not None
        and profit_series[index - 1] not in (None, 0)
        and profit_series[index - 1] > 0
    ]
    volatility = pstdev(profit_growths) if len(profit_growths) >= 2 else None
    turned_profitable = any(
        value is not None and value < 0 for value in profit_series[:-1]
    ) and (profit_series[-1] or 0) > 0

    history = _historical_pe(annual, candles, trading, reporting, rates, symbol)
    scale = price_scale(symbol)
    price_in_reporting = (
        last_price * scale
        if trading == reporting
        else convert(last_price * scale, trading, reporting, rates)
    )
    shares = _shares_series(annual)
    book_per_share = (
        (_number((annual[-1].get("metrics") or {}).get("stockholders_equity")) or 0) / shares[-1]
        if shares and shares[-1]
        else None
    )
    pbv = (
        price_in_reporting / book_per_share
        if price_in_reporting and book_per_share and book_per_share > 0
        else None
    )

    stages = [
        _stage_growth(annual, years),
        _stage_quality(annual),
        _stage_efficiency(annual),
        _stage_management(annual, years),
    ]
    passed_stages = sum(1 for stage in stages if stage["passed"])

    analyst_fair_value = _number(research.get("fair_value")) or 0.0
    analyst_fair_reporting = None
    if analyst_fair_value:
        analyst_fair_reporting = (
            analyst_fair_value * scale
            if trading == reporting
            else convert(analyst_fair_value * scale, trading, reporting, rates)
        )

    eps_cagr = _cagr(eps_series[-1], eps_series[0], years)
    methods = _valuation_methods(
        annual, history, eps_series[-1], eps_cagr, analyst_fair_reporting
    )
    estimates = [
        method["fair_value"]
        for method in methods
        if method.get("fair_value") and not method.get("is_floor") and not method.get("skipped")
    ]
    fair_value = median(estimates) if estimates else None
    spread = max(estimates) / min(estimates) if len(estimates) > 1 and min(estimates) > 0 else 1.0
    estimates_agree = spread <= VALUATION_SPREAD_LIMIT
    margin_of_safety = (
        (fair_value - price_in_reporting) / fair_value * 100
        if fair_value and price_in_reporting and fair_value > 0
        else None
    )

    failed = [stage["title"] for stage in stages if not stage["passed"]]
    quality_ok = not failed
    price_ok = (
        margin_of_safety is not None
        and margin_of_safety >= MARGIN_OF_SAFETY_TARGET
        and estimates_agree
    )
    if not quality_ok:
        verdict_key, verdict = "avoid", "ยังไม่ผ่านคุณภาพ - ข้าม"
        verdict_note = (
            f"ตกด่าน {', '.join(failed)} ธุรกิจยังไม่ผ่าน Financial Quality Filter "
            "ราคาถูกแค่ไหนก็ยังไม่ใช่เหตุผลให้ซื้อ"
        )
    elif margin_of_safety is None:
        verdict_key, verdict = "wait", "คุณภาพผ่าน แต่ประเมินมูลค่าไม่ได้ - รอ"
        verdict_note = "ผ่านคุณภาพครบทุกด่าน แต่ยังคำนวณมูลค่าที่เหมาะสมไม่ได้ จึงยังไม่รู้ว่าราคานี้คุ้มหรือไม่"
    elif not estimates_agree:
        verdict_key, verdict = "wait", "คุณภาพผ่าน แต่มูลค่ายังไม่ชัด - รอ"
        verdict_note = (
            f"วิธีประเมินมูลค่าให้ผลห่างกัน {spread:.1f} เท่า ตัวเลขกลางจึงยังไม่น่าเชื่อถือพอ "
            "ต้องเลือกวิธีที่เหมาะกับหุ้นประเภทนี้ก่อน"
        )
    elif price_ok:
        verdict_key, verdict = "buy", "บริษัทดี ราคาดี - เข้าเงื่อนไขซื้อ"
        verdict_note = "ผ่านทั้งคุณภาพธุรกิจและส่วนลดความปลอดภัย เหลือเพียงตรวจเชิงคุณภาพและจังหวะเข้า"
    else:
        verdict_key, verdict = "wait", "บริษัทดี แต่แพง - รอ"
        verdict_note = "คุณภาพผ่านแล้ว แต่ราคายังไม่ให้ส่วนลดพอ การรอไม่ใช่การพลาดโอกาส"

    checklist = [
        {
            "label": "คุณภาพธุรกิจดี ผ่าน Financial Quality Filter",
            "passed": quality_ok,
            "detail": f"ผ่าน {passed_stages} จาก {len(stages)} ด่าน"
            + (f" · ตกด่าน {', '.join(failed)}" if failed else ""),
        },
        {
            "label": "การเงินแข็งแกร่ง เติบโตต่อเนื่อง",
            "passed": stages[0]["passed"] and stages[1]["passed"],
            "detail": "ดูจากด่าน Growth และ Quality",
        },
        {
            "label": "ราคาต่ำกว่ามูลค่าที่เหมาะสม",
            "passed": bool(margin_of_safety is not None and margin_of_safety > 0),
            "detail": (
                f"ราคา {price_in_reporting:.2f} เทียบมูลค่า {fair_value:.2f} {reporting}"
                if fair_value and price_in_reporting
                else "ประเมินมูลค่าไม่ได้"
            ),
        },
        {
            "label": f"Margin of Safety มากกว่า {MARGIN_OF_SAFETY_TARGET:.0f}%",
            "passed": bool(price_ok),
            "detail": (
                f"ตอนนี้อยู่ที่ {margin_of_safety:.1f}%"
                if margin_of_safety is not None
                else "คำนวณไม่ได้"
            ),
        },
    ]

    profile.update(
        {
            "available": True,
            "reporting_currency": reporting,
            "reporting_currency_label": currency_label(reporting),
            "statement_period": f"{annual[0]['period_end'][:4]}-{annual[-1]['period_end'][:4]}",
            "as_of": annual[-1].get("period_end", ""),
            "price_in_reporting": round(price_in_reporting, 4) if price_in_reporting else None,
            "fx_adjusted": bool(price_in_reporting and trading != reporting),
            "lynch_type": _lynch_type(
                _cagr(revenue_series[-1], revenue_series[0], years),
                _cagr(profit_series[-1], profit_series[0], years),
                roe_series[-1] if roe_series else None,
                pbv,
                volatility,
                turned_profitable,
                0,
            ),
            "stages": stages,
            "passed_stages": passed_stages,
            "total_stages": len(stages),
            "series_summary": _series_summary(annual, reporting),
            "series": {
                "years": [str(period.get("period_end"))[:4] for period in annual],
                "revenue": revenue_series,
                "net_income": profit_series,
                "eps": eps_series,
                "roe": roe_series,
                "roic": _roic_series(annual),
                "operating_cash_flow": _series(annual, "operating_cash_flow"),
                "free_cash_flow": _series(annual, "free_cash_flow"),
                "debt_to_equity": _ratio_series(annual, "debt_to_equity"),
                "gross_margin": _ratio_series(annual, "gross_margin"),
                "net_margin": _ratio_series(annual, "net_margin"),
                "shares": shares,
            },
            "pe_history": history,
            "valuation": {
                "available": bool(fair_value),
                "methods": methods,
                "fair_value": round(fair_value, 4) if fair_value else None,
                "fair_value_low": round(min(estimates), 4) if estimates else None,
                "fair_value_high": round(max(estimates), 4) if estimates else None,
                "estimates_agree": estimates_agree,
                "spread": round(spread, 2),
                "price": round(price_in_reporting, 4) if price_in_reporting else None,
                "pbv": round(pbv, 2) if pbv else None,
                "book_value_per_share": round(book_per_share, 4) if book_per_share else None,
                "margin_of_safety_pct": round(margin_of_safety, 2) if margin_of_safety is not None else None,
                "target_pct": MARGIN_OF_SAFETY_TARGET,
                "currency": reporting,
                "note": (
                    "ราคาหุ้นถูกแปลงเป็นสกุลเดียวกับงบก่อนเทียบ เพราะบริษัทนี้ซื้อขายคนละสกุลกับที่ยื่นงบ"
                    if trading != reporting
                    else "ราคาและงบเป็นสกุลเดียวกัน จึงเทียบได้โดยตรง"
                ),
            },
            "verdict": {
                "key": verdict_key,
                "label": verdict,
                "note": verdict_note,
                "checklist": checklist,
            },
        }
    )
    return profile


FIVE_FORCES = [
    {
        "number": 1,
        "title": "อำนาจต่อรองจากลูกค้า",
        "english": "Power of Customers",
        "questions": [
            "ลูกค้ามีทางเลือกมากไหม เปลี่ยนไปใช้เจ้าอื่นง่ายหรือเปล่า",
            "ลูกค้ากดราคาได้มากแค่ไหน",
        ],
        "risk": "ลูกค้ามีอำนาจต่อรองสูง จะกดกำไรของธุรกิจลง",
    },
    {
        "number": 2,
        "title": "อำนาจต่อรองจากซัพพลายเออร์",
        "english": "Power of Suppliers",
        "questions": [
            "ซัพพลายเออร์มีน้อยรายหรือไม่",
            "เปลี่ยนซัพพลายเออร์ยากและมีต้นทุนสูงไหม",
        ],
        "risk": "ซัพพลายเออร์มีอำนาจสูง จะดันต้นทุนขึ้นและกำไรลง",
    },
    {
        "number": 3,
        "title": "การคุกคามของผู้เล่นรายใหม่",
        "english": "Threat of New Entrants",
        "questions": [
            "เงินลงทุนเริ่มต้นสูงแค่ไหน มีใบอนุญาตหรือกฎเกณฑ์กั้นไหม",
            "แบรนด์และช่องทางจัดจำหน่ายสร้างใหม่ยากหรือไม่",
        ],
        "risk": "เข้ามาง่าย แปลว่าการแข่งขันจะเพิ่มและกำไรจะลด",
    },
    {
        "number": 4,
        "title": "การคุกคามจากสินค้าทดแทน",
        "english": "Threat of Substitutes",
        "questions": [
            "มีสินค้าหรือบริการอื่นทำหน้าที่แทนได้ไหม",
            "เทคโนโลยีใหม่จะทำให้สินค้านี้ไม่จำเป็นหรือเปล่า",
        ],
        "risk": "สินค้าทดแทนมาก จะกดทั้งยอดขายและกำไร",
    },
    {
        "number": 5,
        "title": "การแข่งขันในอุตสาหกรรม",
        "english": "Industry Rivalry",
        "questions": [
            "คู่แข่งในตลาดมีมากน้อยแค่ไหน และอุตสาหกรรมยังโตอยู่ไหม",
            "แข่งกันที่คุณภาพหรือแข่งกันที่ราคา",
        ],
        "risk": "แข่งกันที่ราคาเป็นหลัก แปลว่ากำไรน้อยและไม่ยั่งยืน",
    },
]

FINANCIAL_QUALITY_FLOW = [
    {"number": 1, "name": "Revenue", "label": "รายได้", "question": "รายได้เติบโตต่อเนื่องหรือไม่ นี่คือจุดเริ่มต้นของทุกอย่าง"},
    {"number": 2, "name": "EPS", "label": "กำไรต่อหุ้น", "question": "กำไรต่อหุ้นเพิ่มขึ้นหรือไม่ สะท้อนความสามารถทำกำไรจริง"},
    {"number": 3, "name": "Profit", "label": "กำไรสุทธิ", "question": "กำไรสุทธิเติบโตสม่ำเสมอและมีคุณภาพหรือไม่"},
    {"number": 4, "name": "ROE", "label": "ผลตอบแทนผู้ถือหุ้น", "question": "สร้างผลตอบแทนให้ผู้ถือหุ้นได้ดีไหม ยิ่งสูงยิ่งดี"},
    {"number": 5, "name": "Cash Flow", "label": "กระแสเงินสด", "question": "เงินสดจากการดำเนินงานเป็นบวกหรือไม่ ธุรกิจสร้างเงินสดได้จริงไหม"},
    {"number": 6, "name": "Debt", "label": "หนี้สิน", "question": "หนี้อยู่ในระดับที่เหมาะสมหรือไม่ หนี้น้อยคือความเสี่ยงต่ำ"},
    {"number": 7, "name": "Margins", "label": "อัตรากำไร", "question": "อัตรากำไรขั้นต้น ดำเนินงาน และสุทธิ ดีขึ้นหรือไม่"},
    {"number": 8, "name": "Insider", "label": "ผู้บริหาร", "question": "ผู้บริหารถือหุ้นหรือไม่ ซื้อเพิ่มหรือทยอยขายทิ้ง"},
]
