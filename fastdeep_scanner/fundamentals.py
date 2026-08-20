from __future__ import annotations

from .models import AgentInsight, FundamentalSnapshot


def _bounded(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def financial_score(snapshot: FundamentalSnapshot) -> tuple[float, list[str], list[str]]:
    score = 0.0
    bullets: list[str] = []
    warnings: list[str] = []

    if snapshot.roe >= 20:
        score += 22
        bullets.append(f"ROE is strong at {snapshot.roe:.1f}%")
    elif snapshot.roe >= 12:
        score += 15
        bullets.append(f"ROE is acceptable at {snapshot.roe:.1f}%")
    else:
        score += 5
        warnings.append(f"ROE is weak at {snapshot.roe:.1f}%")

    if snapshot.roa >= 8:
        score += 14
        bullets.append(f"ROA is healthy at {snapshot.roa:.1f}%")
    elif snapshot.roa >= 4:
        score += 8
    else:
        warnings.append(f"ROA is low at {snapshot.roa:.1f}%")

    if snapshot.debt_to_equity <= 0.8:
        score += 16
        bullets.append(f"Debt/equity is controlled at {snapshot.debt_to_equity:.2f}x")
    elif snapshot.debt_to_equity <= 1.8:
        score += 9
    else:
        score += 2
        warnings.append(f"Debt/equity is high at {snapshot.debt_to_equity:.2f}x")

    growth = (snapshot.revenue_growth + snapshot.profit_growth) / 2
    if growth >= 15:
        score += 20
        bullets.append(f"Revenue/profit growth averages {growth:.1f}%")
    elif growth >= 5:
        score += 12
        bullets.append(f"Growth is positive at {growth:.1f}%")
    elif growth >= 0:
        score += 6
    else:
        warnings.append(f"Growth is negative at {growth:.1f}%")

    if snapshot.net_margin >= 18:
        score += 15
        bullets.append(f"Net margin is high at {snapshot.net_margin:.1f}%")
    elif snapshot.net_margin >= 8:
        score += 9
    else:
        warnings.append(f"Net margin is thin at {snapshot.net_margin:.1f}%")

    if snapshot.liquidity_score >= 70:
        score += 13
        bullets.append("Liquidity is suitable for execution")
    elif snapshot.liquidity_score >= 40:
        score += 7
    else:
        warnings.append("Liquidity score is low")

    return _bounded(score), bullets, warnings


def business_score(snapshot: FundamentalSnapshot) -> tuple[float, list[str]]:
    score = 44.0
    bullets: list[str] = []
    moat_map = {
        "wide": 24,
        "strong": 20,
        "medium": 14,
        "niche": 12,
        "weak": 3,
    }
    ai_map = {
        "leader": 20,
        "beneficiary": 15,
        "automation": 11,
        "neutral": 5,
        "laggard": 0,
    }
    moat_bonus = moat_map.get(snapshot.moat.lower(), 8)
    ai_bonus = ai_map.get(snapshot.ai_trend.lower(), 5)
    score += moat_bonus + ai_bonus
    bullets.append(f"Moat profile: {snapshot.moat}")
    bullets.append(f"AI/automation trend: {snapshot.ai_trend}")
    if snapshot.sector.lower() in {"semiconductors", "software", "digital infrastructure"}:
        score += 6
        bullets.append("Sector has structural technology tailwind")
    return _bounded(score), bullets


def valuation_score(
    snapshot: FundamentalSnapshot,
    valuation: dict | None = None,
) -> tuple[float, list[str], list[str]]:
    """Score the price paid using multiples derived from the filed statements.

    Nothing here falls back to an assumed P/E or upside: when the multiple could
    not be derived the caller is told so instead of being handed a number.
    """
    valuation = valuation or {}
    if not valuation.get("verified"):
        note = valuation.get("note") or "ยังไม่มีข้อมูลพอสำหรับประเมินมูลค่า"
        return 0.0, [note], []

    score = 50.0
    bullets: list[str] = []
    warnings: list[str] = []
    reporting = valuation.get("reporting_currency") or ""
    pe = valuation.get("pe")
    pbv = valuation.get("pbv")
    upside = valuation.get("upside_pct")
    growth = max(0.0, (snapshot.revenue_growth + snapshot.profit_growth) / 2)

    if pe is None:
        score -= 8
        warnings.append("ไม่มี P/E เพราะบริษัทยังไม่มีกำไรต่อหุ้นเป็นบวก")
    elif pe <= 12:
        score += 18
        bullets.append(f"P/E {pe:.1f} เท่า ถูกเมื่อเทียบกับกำไรที่รายงานจริง ({reporting})")
    elif pe <= 20:
        score += 12
        bullets.append(f"P/E {pe:.1f} เท่า อยู่ในระดับสมเหตุสมผล ({reporting})")
    elif pe <= 32:
        score += 5
        bullets.append(f"P/E {pe:.1f} เท่า เริ่มตึงแต่ยังรับได้ถ้ากำไรโต")
    else:
        score -= 6
        warnings.append(f"P/E สูงถึง {pe:.1f} เท่า ต้องมีการเติบโตรองรับชัดเจน")

    if pe is not None and growth > 0:
        peg = pe / growth
        if peg <= 1.0:
            score += 8
            bullets.append(f"PEG {peg:.2f} ราคายังตามหลังการเติบโต")
        elif peg > 2.5:
            score -= 4
            warnings.append(f"PEG {peg:.2f} ราคาวิ่งไปไกลกว่าการเติบโต")

    if pbv is None:
        warnings.append("คำนวณ P/BV ไม่ได้จากงบชุดนี้")
    elif pbv <= 1.5:
        score += 12
        bullets.append(f"P/BV {pbv:.2f} เท่า ต่ำกว่ามูลค่าทางบัญชีที่ 1.5 เท่า")
    elif pbv <= 3.0:
        score += 8
    elif pbv <= 6.0:
        score += 2
    else:
        score -= 6
        warnings.append(f"P/BV {pbv:.2f} เท่า แพงเมื่อเทียบมูลค่าทางบัญชี")

    if upside is None:
        bullets.append("ยังไม่ได้บันทึกมูลค่าที่เหมาะสมของนักวิเคราะห์")
    elif upside >= 25:
        score += 20
        bullets.append(f"ต่ำกว่ามูลค่าที่นักวิเคราะห์ประเมิน {upside:.1f}%")
    elif upside >= 10:
        score += 12
        bullets.append(f"ยังมีส่วนต่างจากมูลค่าที่ประเมินไว้ {upside:.1f}%")
    elif upside < 0:
        score -= 12
        warnings.append(f"ราคาสูงกว่ามูลค่าที่ประเมินไว้ {abs(upside):.1f}%")

    if valuation.get("fx_adjusted"):
        bullets.append(
            f"แปลงราคาจาก {valuation.get('trading_currency')} เป็น {reporting} ก่อนคำนวณมูลค่า"
        )
    return _bounded(score), bullets, warnings


def valuation_verdict(score: float, valuation: dict | None) -> str:
    if not (valuation or {}).get("verified"):
        return "ยังประเมินมูลค่าไม่ได้"
    if score >= 72:
        return "ราคายังต่ำกว่าพื้นฐาน"
    if score >= 55:
        return "ราคาเหมาะสม"
    return "ราคาแพงเทียบพื้นฐาน"


def financial_insight(score: float, bullets: list[str], warnings: list[str]) -> AgentInsight:
    label = "Strong" if score >= 75 else "Check" if score >= 55 else "Weak"
    summary = "Financials support the setup" if score >= 65 else "Financials need caution"
    return AgentInsight(
        agent="Financial Analysis Agent",
        score=score,
        label=label,
        summary=summary,
        bullets=bullets[:4] + warnings[:2],
    )


def business_insight(score: float, bullets: list[str]) -> AgentInsight:
    label = "Quality" if score >= 75 else "Neutral" if score >= 55 else "Low quality"
    return AgentInsight(
        agent="Business Quality Agent",
        score=score,
        label=label,
        summary="Moat and trend quality assessment",
        bullets=bullets[:4],
    )


def valuation_insight(score: float, bullets: list[str], warnings: list[str]) -> AgentInsight:
    label = "Attractive" if score >= 72 else "Fair" if score >= 55 else "Expensive"
    return AgentInsight(
        agent="Valuation Agent",
        score=score,
        label=label,
        summary="Upside and valuation sanity check",
        bullets=bullets[:3] + warnings[:2],
    )
