from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, date, datetime

from .currency import currency_label, load_fx_rates
from .data_health import expected_eod_date
from .data_io import completed_eod_candles, load_market_data
from .evidence import best_evidence
from .fundamentals import (
    business_insight,
    business_score,
    financial_insight,
    financial_score,
    valuation_insight,
    valuation_score,
    valuation_verdict,
)
from .liquidity import liquidity_profile
from .models import AgentInsight, FundamentalSnapshot, ScanCriteria, ScanResult, StockCandle
from .patterns import detect_patterns, market_phase, technical_context_score
from .risk import build_risk_plan
from .timeframes import aggregate_candles, normalize_timeframe
from .valuation import derive_valuation


VERIFICATION_LABELS = {
    "technical": "ตรวจแล้วเฉพาะกราฟ",
    "financial": "ตรวจกราฟและงบการเงิน",
    "valuation": "ตรวจกราฟ งบ และมูลค่า",
    "full": "ตรวจครบทุกด้านรวมคุณภาพธุรกิจ",
}


def _grade(score: float) -> str:
    if score >= 88:
        return "A+"
    if score >= 78:
        return "A"
    if score >= 68:
        return "B"
    if score >= 58:
        return "C"
    return "D"


def _decision(
    score: float,
    warnings: list[str],
    has_bearish: bool,
    fundamentals_verified: bool,
    valuation_verified: bool,
    research_verified: bool,
    evidence_tradeable: bool,
) -> str:
    if has_bearish:
        return "Reject long / watch breakdown"
    if not fundamentals_verified:
        return "รอตรวจงบการเงิน"
    if not valuation_verified:
        return "รอประเมินมูลค่า"
    if not research_verified:
        return "รอบทวิเคราะห์ธุรกิจ"
    # A pattern with no measured edge over buy-and-hold never reaches Candidate,
    # however good the chart and the books look.
    if score >= 82 and not warnings and evidence_tradeable:
        return "Candidate"
    if score >= 72:
        return "Watchlist"
    if score >= 60:
        return "Needs confirmation"
    return "Reject"


def _technical_insight(score: float, reasons: list[str], patterns: list) -> AgentInsight:
    if patterns:
        names = ", ".join(pattern.label for pattern in patterns)
        summary = f"Pattern detected: {names}"
    else:
        summary = "No selected pattern has triggered"
    label = "A setup" if score >= 78 else "Watch" if score >= 58 else "Weak"
    bullets = [reason for pattern in patterns for reason in pattern.reasons[:2]]
    bullets.extend(reasons[:3])
    return AgentInsight(
        agent="Technical Pattern Agent",
        score=score,
        label=label,
        summary=summary,
        bullets=bullets[:5],
    )


def _market_scanner_insight(result_count: int, best_score: float) -> AgentInsight:
    label = "Active" if result_count else "Quiet"
    summary = f"Scanner found {result_count} symbols above filters"
    return AgentInsight(
        agent="Market Scanner Agent",
        score=best_score,
        label=label,
        summary=summary,
        bullets=[
            "Scan sequence: chart pattern first, fundamentals second, risk plan last",
            "Patterns covered: breakout, retest, cup & handle, double bottom, head & shoulders",
        ],
    )


def _report_writer_insight(result: ScanResult) -> AgentInsight:
    return AgentInsight(
        agent="Report Writer Agent",
        score=result.final_score,
        label=result.grade,
        summary=f"{result.symbol} is classified as {result.decision}",
        bullets=[
            f"Technical {result.technical_score:.1f}, financial {result.fundamental_score:.1f}",
            f"Business {result.business_score:.1f}, valuation {result.valuation_score:.1f}",
            "Use the PDF report button for NotebookLM or presentation workflow",
        ],
    )


def _decision_summary(
    *,
    snapshot: FundamentalSnapshot,
    patterns: list,
    tech_score: float,
    fin_score: float,
    val_score: float,
    valuation: dict,
    risk_plan,
    liquidity: dict,
    has_bearish: bool,
    timeframe: str,
    evidence: dict,
) -> dict:
    """The one block an analyst reads before deciding: setup, books, price, risk."""
    pattern_label = ", ".join(pattern.label for pattern in patterns) or "-"
    entry = risk_plan.entry
    stop = risk_plan.stop
    risk_pct = risk_plan.risk_pct
    trading = snapshot.trading_currency or ""
    reporting = snapshot.reporting_currency or ""

    if snapshot.fundamentals_verified:
        financial_state = "งบยืนยันแล้ว" if fin_score >= 55 else "งบยืนยันแล้วแต่คุณภาพอ่อน"
        financial_detail = (
            f"ROE {snapshot.roe:.1f}% · D/E {snapshot.debt_to_equity:.2f} เท่า · "
            f"รายได้โต {snapshot.revenue_growth:.1f}% · งวด {snapshot.as_of or '-'} "
            f"· สกุลงบ {currency_label(reporting)}"
        )
    else:
        financial_state = "รอตรวจงบ"
        financial_detail = "ยังไม่มีงบการเงินยืนยัน จึงไม่ให้คะแนนพื้นฐาน"

    return {
        "technical": {
            "pass": bool(patterns) and not has_bearish,
            "label": "Technical ผ่าน" if patterns and not has_bearish else "Technical ไม่ผ่าน",
            "detail": f"{pattern_label} · คะแนนเทคนิค {tech_score:.1f} · Timeframe {timeframe}",
        },
        "financials": {
            "verified": snapshot.fundamentals_verified,
            "label": financial_state,
            "detail": financial_detail,
        },
        "valuation": {
            "verified": bool(valuation.get("verified")),
            "label": valuation_verdict(val_score, valuation),
            "detail": (
                f"P/E {valuation['pe']:.1f} เท่า · P/BV {valuation['pbv']:.2f} เท่า · {valuation.get('note', '')}"
                if valuation.get("verified") and valuation.get("pe") and valuation.get("pbv")
                else valuation.get("note") or "ยังประเมินมูลค่าไม่ได้"
            ),
        },
        "risk": {
            "label": f"ตัดขาดทุนที่ {stop:.2f} {trading} (เสี่ยง {risk_pct:.1f}% ต่อไม้)",
            "wide": risk_pct > 12.0,
            "detail": (
                f"เข้า {entry:.2f} {trading} · เป้าหมายแรก {risk_plan.targets[0]:.2f} · "
                f"R:R {risk_plan.reward_risk:.2f} · สภาพคล่องกลางวันละ "
                f"{(liquidity.get('turnover_usd') or 0) / 1_000_000:.1f} ล้าน USD · {risk_plan.sizing_note}"
            ),
        },
        "evidence": {
            "tradeable": bool(evidence.get("tradeable")),
            "label": evidence.get("label", "-"),
            "pattern": evidence.get("pattern", ""),
        },
        "research_status": snapshot.research_status,
        "thesis": snapshot.thesis,
    }


def _scan_symbol(
    daily_candles: list[StockCandle],
    snapshot: FundamentalSnapshot,
    criteria: ScanCriteria,
    fx_rates: dict[str, float] | None = None,
    expected_eod: date | None = None,
) -> ScanResult | None:
    timeframe = normalize_timeframe(criteria.timeframe)
    candles = aggregate_candles(daily_candles, timeframe)
    minimum_bars = 50 if timeframe == "M" else 90
    if len(candles) < minimum_bars:
        return None
    if criteria.market != "ALL" and snapshot.market.upper() != criteria.market.upper():
        return None
    if criteria.universe != "ALL":
        groups = {group.strip().upper() for group in snapshot.index_groups.split("|") if group.strip()}
        if criteria.universe.upper() not in groups:
            return None

    liquidity = liquidity_profile(daily_candles, snapshot.symbol, snapshot.market, rates=fx_rates)
    if float(liquidity["score"]) < criteria.min_liquidity:
        return None
    snapshot = replace(
        snapshot,
        liquidity_score=float(liquidity["score"]),
        turnover_usd=float(liquidity.get("turnover_usd") or 0.0),
        liquidity_note=str(liquidity.get("note") or ""),
    )

    patterns = detect_patterns(candles, criteria.patterns, timeframe)
    if not patterns:
        return None

    # A symbol can go quiet inside a feed that reports fresh overall. Scoring a
    # halted or delisted name against a month-old chart is worse than skipping it.
    price_as_of = daily_candles[-1].date
    price_is_fresh = expected_eod is None or price_as_of >= expected_eod
    evidence = best_evidence([pattern.name for pattern in patterns], timeframe)
    # Patterns are read off completed weekly or monthly bars, but the trade is
    # entered and stopped out on daily prices. Using the aggregated close would
    # value the stock at last month's print and size the stop off a monthly ATR.
    last_price = daily_candles[-1].close
    tech_score, tech_reasons = technical_context_score(candles, patterns)
    valuation = derive_valuation(snapshot, last_price, fx_rates)
    snapshot = replace(
        snapshot,
        pe=float(valuation.get("pe") or 0.0),
        pbv=float(valuation.get("pbv") or 0.0),
        analyst_upside_pct=float(valuation.get("upside_pct") or 0.0),
        valuation_verified=bool(valuation.get("verified")),
        valuation_note=str(valuation.get("note") or ""),
    )

    fin_score, fin_bullets, fin_warnings = (
        financial_score(snapshot) if snapshot.fundamentals_verified else (0.0, [], [])
    )
    val_score, val_bullets, val_warnings = valuation_score(snapshot, valuation)
    if snapshot.research_verified:
        biz_score, biz_bullets = business_score(snapshot)
    else:
        biz_score, biz_bullets = 0.0, ["ยังไม่มีนักวิเคราะห์บันทึก Moat และแนวโน้มธุรกิจ"]

    # Weights shift onto whatever has actually been verified, so an unverified
    # leg never contributes a zero that silently drags the score down. The cap
    # then keeps an unchecked chart from outranking a fully researched name -
    # without it a pure pattern hit scored 100 and sat at the top of the table.
    if snapshot.fundamentals_verified and snapshot.valuation_verified and snapshot.research_verified:
        final_score = tech_score * 0.38 + fin_score * 0.27 + val_score * 0.20 + biz_score * 0.15
        verification_level, score_cap = "full", 100.0
    elif snapshot.fundamentals_verified and snapshot.valuation_verified:
        final_score = tech_score * 0.46 + fin_score * 0.32 + val_score * 0.22
        verification_level, score_cap = "valuation", 90.0
    elif snapshot.fundamentals_verified:
        final_score = tech_score * 0.60 + fin_score * 0.40
        verification_level, score_cap = "financial", 82.0
    else:
        final_score = tech_score
        verification_level, score_cap = "technical", 72.0
    final_score = min(final_score, score_cap)

    has_bearish = any(pattern.side == "SELL" for pattern in patterns)
    if has_bearish:
        final_score = min(final_score, 62)

    warnings = list(fin_warnings) + list(val_warnings)
    if has_bearish:
        warnings.append("Bearish chart structure appears before buy decision")
    if snapshot.fundamentals_verified and fin_score < 55:
        warnings.append("คุณภาพพื้นฐานยังไม่ยืนยันภาพทางเทคนิค")
    if not snapshot.fundamentals_verified:
        warnings.append("ยังไม่ได้ตรวจงบการเงิน ผลนี้เป็นสัญญาณทางเทคนิคเท่านั้น")
    if not snapshot.valuation_verified:
        warnings.append(snapshot.valuation_note or "ยังประเมินมูลค่าไม่ได้")
    if not snapshot.research_verified:
        warnings.append("ต้องให้นักวิเคราะห์บันทึกคุณภาพธุรกิจก่อนอนุมัติ")
    if not evidence.get("tradeable"):
        warnings.append(f"หลักฐานย้อนหลัง: {evidence.get('label', 'ยังไม่ได้ทดสอบ')}")
    if not price_is_fresh:
        warnings.append(
            f"ราคาล่าสุดของหุ้นตัวนี้อยู่ที่ {price_as_of.isoformat()} ซึ่งเก่ากว่าวัน EOD ที่ใช้สแกน "
            "อาจถูกพักการซื้อขายหรือหลุดจากผู้ให้บริการ"
        )
    if verification_level != "full":
        warnings.append(
            f"คะแนนถูกจำกัดไว้ที่ {score_cap:.0f} เพราะยังตรวจไม่ครบทุกด้าน ({VERIFICATION_LABELS[verification_level]})"
        )
    if snapshot.turnover_usd and snapshot.turnover_usd < 1_000_000:
        warnings.append(
            f"สภาพคล่องบางเพียง {snapshot.turnover_usd / 1_000_000:.2f} ล้าน USD ต่อวัน ระวังขนาดไม้"
        )

    if final_score < criteria.min_score:
        return None

    fully_verified = (
        snapshot.fundamentals_verified and snapshot.valuation_verified and snapshot.research_verified
    )
    risk_plan = build_risk_plan(daily_candles, patterns)
    base_insights = [
        _technical_insight(tech_score, tech_reasons, patterns),
        financial_insight(fin_score, fin_bullets, fin_warnings)
        if snapshot.fundamentals_verified
        else AgentInsight(
            agent="Financial Analysis Agent",
            score=0.0,
            label="Pending",
            summary="ยังไม่มีงบการเงินยืนยันของหุ้นตัวนี้",
            bullets=["เปิดแท็บงบการเงินเพื่อดึงและยืนยันข้อมูลงวดล่าสุด"],
        ),
        business_insight(biz_score, biz_bullets),
        valuation_insight(val_score, val_bullets, val_warnings),
    ]
    result = ScanResult(
        symbol=snapshot.symbol,
        name=snapshot.name,
        market=snapshot.market,
        sector=snapshot.sector,
        index_groups=snapshot.index_groups,
        last_price=last_price,
        market_phase=market_phase(candles),
        technical_score=tech_score,
        fundamental_score=fin_score,
        business_score=biz_score,
        valuation_score=val_score,
        final_score=final_score,
        grade=_grade(final_score) if fully_verified else f"T-{_grade(final_score)}",
        decision="ข้อมูลราคาไม่สด"
        if not price_is_fresh
        else _decision(
            final_score,
            warnings,
            has_bearish,
            snapshot.fundamentals_verified,
            snapshot.valuation_verified,
            snapshot.research_verified,
            bool(evidence.get("tradeable")),
        ),
        patterns=patterns,
        risk_plan=risk_plan,
        insights=base_insights,
        warnings=warnings,
        fundamentals_verified=snapshot.fundamentals_verified,
        research_verified=snapshot.research_verified,
        valuation_verified=snapshot.valuation_verified,
        research_status=snapshot.research_status,
        verification_level=verification_level,
        score_cap=score_cap,
        liquidity_score=snapshot.liquidity_score,
        turnover_usd=snapshot.turnover_usd,
        currency=snapshot.trading_currency,
        reporting_currency=snapshot.reporting_currency,
        price_as_of=price_as_of.isoformat(),
        price_is_fresh=price_is_fresh,
        evidence=evidence,
        decision_summary=_decision_summary(
            snapshot=snapshot,
            patterns=patterns,
            tech_score=tech_score,
            fin_score=fin_score,
            val_score=val_score,
            valuation=valuation,
            risk_plan=risk_plan,
            liquidity=liquidity,
            has_bearish=has_bearish,
            timeframe=timeframe,
            evidence=evidence,
        ),
        timeframe=timeframe,
        generated_at=datetime.now(UTC),
    )
    return ScanResult(
        **{
            **result.__dict__,
            "insights": base_insights + [_report_writer_insight(result)],
        }
    )


def scan_market(
    criteria: ScanCriteria | None = None,
    market_data_path: str | None = None,
    fundamentals_path: str | None = None,
) -> list[ScanResult]:
    criteria = criteria or ScanCriteria()
    candles_by_symbol, fundamentals = load_market_data(market_data_path, fundamentals_path)
    fx_rates = load_fx_rates().get("rates", {})
    sample_mode = os.environ.get("FASTDEEP_USE_SAMPLE_DATA") == "1"
    expected_eod = None if sample_mode else expected_eod_date()
    results: list[ScanResult] = []
    for symbol, candles in candles_by_symbol.items():
        snapshot = fundamentals.get(symbol)
        if snapshot is None:
            continue
        scan_candles = candles if sample_mode else completed_eod_candles(candles)
        if not scan_candles:
            continue
        result = _scan_symbol(scan_candles, snapshot, criteria, fx_rates, expected_eod)
        if result is not None:
            results.append(result)
    return sorted(results, key=lambda item: item.final_score, reverse=True)


def scanner_overview(criteria: ScanCriteria | None = None) -> dict:
    results = scan_market(criteria)
    best = results[0].final_score if results else 0.0
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "criteria": (criteria or ScanCriteria()).__dict__,
        "scanner_agent": _market_scanner_insight(len(results), best).to_dict(),
        "results": [result.to_dict() for result in results],
    }
