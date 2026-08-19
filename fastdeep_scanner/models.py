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

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "symbol": self.symbol,
            "open": round(self.open, 4),
            "high": round(self.high, 4),
            "low": round(self.low, 4),
            "close": round(self.close, 4),
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "bias": self.bias,
            "entry": round(self.entry, 4),
            "stop": round(self.stop, 4),
            "targets": [round(target, 4) for target in self.targets],
            "reward_risk": round(self.reward_risk, 2),
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
        "head_shoulders",
    )
    min_score: float = 55.0
    min_liquidity: float = 40.0


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
            "generated_at": self.generated_at.isoformat(),
        }
