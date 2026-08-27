from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any


@dataclass(frozen=True)
class StockCandle:
    date: date
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    adjusted_close: float | None = None
    adjusted_open: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "symbol": self.symbol,
            "open": round(self.open, 4),
            "high": round(self.high, 4),
            "low": round(self.low, 4),
            "close": round(self.close, 4),
            "adjusted_close": round(self.adjusted_close, 4) if self.adjusted_close is not None else None,
            "adjusted_open": round(self.adjusted_open, 4) if self.adjusted_open is not None else None,
            "volume": round(self.volume, 2),
        }


@dataclass(frozen=True)
class FundamentalSnapshot:
    symbol: str
    name: str
    market: str
    sector: str
    roe: float
    roa: float
    debt_to_equity: float
    revenue_growth: float
    profit_growth: float
    gross_margin: float
    net_margin: float
    pe: float
    pbv: float
    dividend_yield: float
    analyst_upside_pct: float
    liquidity_score: float
    moat: str
    ai_trend: str
    notes: str = ""
    index_groups: str = ""
    fundamentals_verified: bool = True
    research_verified: bool = True
    source: str = ""
    as_of: str = ""
    eps: float = 0.0
    book_value_per_share: float = 0.0
    reporting_currency: str = ""
    trading_currency: str = ""
    valuation_verified: bool = False
    valuation_note: str = ""
    analyst_fair_value: float = 0.0
    thesis: str = ""
    research_status: str = "Watch"
    turnover_usd: float = 0.0
    liquidity_note: str = ""
    financial_history_complete: bool = False
    financial_history_status: str = "missing"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "market": self.market,
            "sector": self.sector,
            "roe": self.roe,
            "roa": self.roa,
            "debt_to_equity": self.debt_to_equity,
            "revenue_growth": self.revenue_growth,
            "profit_growth": self.profit_growth,
            "gross_margin": self.gross_margin,
            "net_margin": self.net_margin,
            "pe": self.pe,
            "pbv": self.pbv,
            "dividend_yield": self.dividend_yield,
            "analyst_upside_pct": self.analyst_upside_pct,
            "liquidity_score": self.liquidity_score,
            "moat": self.moat,
            "ai_trend": self.ai_trend,
            "notes": self.notes,
            "index_groups": self.index_groups,
            "fundamentals_verified": self.fundamentals_verified,
            "research_verified": self.research_verified,
            "source": self.source,
            "as_of": self.as_of,
            "eps": self.eps,
            "book_value_per_share": self.book_value_per_share,
            "reporting_currency": self.reporting_currency,
            "trading_currency": self.trading_currency,
            "valuation_verified": self.valuation_verified,
            "valuation_note": self.valuation_note,
            "analyst_fair_value": self.analyst_fair_value,
            "thesis": self.thesis,
            "research_status": self.research_status,
            "turnover_usd": self.turnover_usd,
            "liquidity_note": self.liquidity_note,
            "financial_history_complete": self.financial_history_complete,
            "financial_history_status": self.financial_history_status,
        }


@dataclass(frozen=True)
class PatternHit:
    name: str
    label: str
    side: str
    score: float
    confidence: float
    level: float
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "side": self.side,
            "score": round(self.score, 2),
            "confidence": round(self.confidence, 2),
            "level": round(self.level, 4),
            "reasons": self.reasons,
        }


@dataclass(frozen=True)
class RiskPlan:
    bias: str
    entry: float
    stop: float
    targets: list[float]
    reward_risk: float
    invalidation: str
    sizing_note: str
    risk_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "bias": self.bias,
            "entry": round(self.entry, 4),
            "stop": round(self.stop, 4),
            "targets": [round(target, 4) for target in self.targets],
            "reward_risk": round(self.reward_risk, 2),
            "risk_pct": round(self.risk_pct, 2),
            "invalidation": self.invalidation,
            "sizing_note": self.sizing_note,
        }


@dataclass(frozen=True)
class AgentInsight:
    agent: str
    score: float
    label: str
    summary: str
    bullets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "score": round(self.score, 2),
            "label": self.label,
            "summary": self.summary,
            "bullets": self.bullets,
        }


@dataclass(frozen=True)
class ScanCriteria:
    market: str = "ALL"
    universe: str = "ALL"
    patterns: tuple[str, ...] = (
        "breakout",
        "retest",
        "cup_handle",
        "double_bottom",
    )
    min_score: float = 70.0
    min_liquidity: float = 40.0
    timeframe: str = "D"


@dataclass(frozen=True)
class ScanResult:
    symbol: str
    name: str
    market: str
    sector: str
    index_groups: str
    last_price: float
    market_phase: str
    technical_score: float
    fundamental_score: float
    business_score: float
    valuation_score: float
    final_score: float
    grade: str
    decision: str
    patterns: list[PatternHit]
    risk_plan: RiskPlan
    insights: list[AgentInsight]
    warnings: list[str] = field(default_factory=list)
    fundamentals_verified: bool = False
    financial_history_complete: bool = False
    research_verified: bool = False
    valuation_verified: bool = False
    research_status: str = "Watch"
    verification_level: str = "technical"
    score_cap: float = 72.0
    liquidity_score: float = 0.0
    turnover_usd: float = 0.0
    currency: str = ""
    reporting_currency: str = ""
    price_as_of: str = ""
    price_is_fresh: bool = True
    evidence: dict[str, Any] = field(default_factory=dict)
    decision_summary: dict[str, Any] = field(default_factory=dict)
    timeframe: str = "D"
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "market": self.market,
            "sector": self.sector,
            "index_groups": self.index_groups,
            "last_price": round(self.last_price, 4),
            "market_phase": self.market_phase,
            "technical_score": round(self.technical_score, 2),
            "fundamental_score": round(self.fundamental_score, 2),
            "business_score": round(self.business_score, 2),
            "valuation_score": round(self.valuation_score, 2),
            "final_score": round(self.final_score, 2),
            "grade": self.grade,
            "decision": self.decision,
            "patterns": [pattern.to_dict() for pattern in self.patterns],
            "risk_plan": self.risk_plan.to_dict(),
            "insights": [insight.to_dict() for insight in self.insights],
            "warnings": self.warnings,
            "fundamentals_verified": self.fundamentals_verified,
            "financial_history_complete": self.financial_history_complete,
            "research_verified": self.research_verified,
            "valuation_verified": self.valuation_verified,
            "research_status": self.research_status,
            "verification_level": self.verification_level,
            "score_cap": self.score_cap,
            "liquidity_score": round(self.liquidity_score, 1),
            "turnover_usd": round(self.turnover_usd, 2),
            "currency": self.currency,
            "reporting_currency": self.reporting_currency,
            "price_as_of": self.price_as_of,
            "price_is_fresh": self.price_is_fresh,
            "evidence": self.evidence,
            "decision_summary": self.decision_summary,
            "timeframe": self.timeframe,
            "generated_at": self.generated_at.isoformat(),
        }
