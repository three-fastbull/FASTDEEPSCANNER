from __future__ import annotations

import os
from datetime import UTC, datetime

from .data_io import completed_eod_candles, load_market_data
from .fundamentals import (
    business_insight,
    business_score,
    financial_insight,
    financial_score,
    valuation_insight,
    valuation_score,
)
from .models import AgentInsight, FundamentalSnapshot, ScanCriteria, ScanResult, StockCandle
from .patterns import detect_patterns, market_phase, technical_context_score
from .risk import build_risk_plan
from .timeframes import aggregate_candles, normalize_timeframe


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
    research_verified: bool,
) -> str:
    if has_bearish:
        return "Reject long / watch breakdown"
    if not research_verified:
        return "Research required"
    if score >= 82 and not warnings:
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


def _scan_symbol(
    candles: list[StockCandle],
    snapshot: FundamentalSnapshot,
    criteria: ScanCriteria,
) -> ScanResult | None:
    timeframe = normalize_timeframe(criteria.timeframe)
    candles = aggregate_candles(candles, timeframe)
    minimum_bars = 50 if timeframe == "M" else 90
    if len(candles) < minimum_bars:
        return None
    if snapshot.liquidity_score < criteria.min_liquidity:
        return None
    if criteria.market != "ALL" and snapshot.market.upper() != criteria.market.upper():
        return None
    if criteria.universe != "ALL":
        groups = {group.strip().upper() for group in snapshot.index_groups.split("|") if group.strip()}
        if criteria.universe.upper() not in groups:
            return None
    patterns = detect_patterns(candles, criteria.patterns, timeframe)
    if not patterns:
        return None

    tech_score, tech_reasons = technical_context_score(candles, patterns)
    fin_score, fin_bullets, fin_warnings = financial_score(snapshot) if snapshot.fundamentals_verified else (0.0, [], [])
    if snapshot.research_verified:
        biz_score, biz_bullets = business_score(snapshot)
        val_score, val_bullets, val_warnings = valuation_score(snapshot)
        final_score = (
            tech_score * 0.42
            + fin_score * 0.30
            + biz_score * 0.18
            + val_score * 0.10
        )
    elif snapshot.fundamentals_verified:
        biz_score, biz_bullets = 0.0, ["Business quality has not been verified"]
        val_score, val_bullets, val_warnings = 0.0, ["Valuation inputs have not been verified"], []
        final_score = tech_score * 0.60 + fin_score * 0.40
    else:
        biz_score, biz_bullets = 0.0, ["Business quality has not been verified"]
        val_score, val_bullets, val_warnings = 0.0, ["Financial and valuation inputs are pending"], []
        final_score = tech_score
    has_bearish = any(pattern.side == "SELL" for pattern in patterns)
    if has_bearish:
        final_score = min(final_score, 62)

    warnings = fin_warnings + val_warnings
    if has_bearish:
        warnings.append("Bearish chart structure appears before buy decision")
    if snapshot.fundamentals_verified and fin_score < 55:
        warnings.append("Fundamental quality does not confirm the chart")
    if not snapshot.fundamentals_verified:
        warnings.append("Financial statements are not verified; this is a technical candidate only.")
    if not snapshot.research_verified:
        warnings.append("Business quality and valuation require analyst review before approval.")

    if final_score < criteria.min_score:
        return None

    base_insights = [
        _technical_insight(tech_score, tech_reasons, patterns),
        financial_insight(fin_score, fin_bullets, fin_warnings)
        if snapshot.fundamentals_verified
        else AgentInsight(
            agent="Financial Analysis Agent",
            score=0.0,
            label="Pending",
            summary="Financial statements have not been verified for this symbol",
            bullets=["Open Financials to fetch and verify the latest statement data"],
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
        last_price=candles[-1].close,
        market_phase=market_phase(candles),
        technical_score=tech_score,
        fundamental_score=fin_score,
        business_score=biz_score,
        valuation_score=val_score,
        final_score=final_score,
        grade=_grade(final_score) if snapshot.research_verified else f"T-{_grade(final_score)}",
        decision=_decision(final_score, warnings, has_bearish, snapshot.research_verified),
        patterns=patterns,
        risk_plan=build_risk_plan(candles, patterns),
        insights=base_insights,
        warnings=warnings,
        fundamentals_verified=snapshot.fundamentals_verified,
        research_verified=snapshot.research_verified,
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
    results: list[ScanResult] = []
    for symbol, candles in candles_by_symbol.items():
        snapshot = fundamentals.get(symbol)
        if snapshot is None:
            continue
        scan_candles = candles if os.environ.get("FASTDEEP_USE_SAMPLE_DATA") == "1" else completed_eod_candles(candles)
        result = _scan_symbol(scan_candles, snapshot, criteria)
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
