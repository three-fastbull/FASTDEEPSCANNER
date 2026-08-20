"""Tradability measured from the price feed instead of a hardcoded constant.

Liquidity decides whether a signal is executable at fund size, so it is derived
from median daily turnover (close x volume) and normalised to USD - a THB and a
USD turnover figure are not comparable numbers.
"""

from __future__ import annotations

from statistics import median

from .currency import to_usd, trading_currency
from .models import StockCandle


# Median daily turnover in USD -> liquidity score. Interpolated in log space so
# the curve is smooth between anchors instead of stepping at each threshold.
_ANCHORS: list[tuple[float, float]] = [
    (20_000, 5.0),
    (100_000, 25.0),
    (500_000, 45.0),
    (2_000_000, 62.0),
    (10_000_000, 80.0),
    (50_000_000, 92.0),
    (250_000_000, 100.0),
]


def median_turnover(candles: list[StockCandle], bars: int = 60) -> float:
    """Median of close x volume over the recent window, in the trading currency."""
    window = [candle for candle in candles[-bars:] if candle.volume > 0 and candle.close > 0]
    if not window:
        return 0.0
    return float(median([candle.close * candle.volume for candle in window]))


def _score_from_usd(turnover_usd: float) -> float:
    if turnover_usd <= 0:
        return 0.0
    if turnover_usd <= _ANCHORS[0][0]:
        return round(_ANCHORS[0][1] * turnover_usd / _ANCHORS[0][0], 1)
    if turnover_usd >= _ANCHORS[-1][0]:
        return 100.0
    from math import log

    for (low_turnover, low_score), (high_turnover, high_score) in zip(_ANCHORS, _ANCHORS[1:]):
        if turnover_usd <= high_turnover:
            ratio = (log(turnover_usd) - log(low_turnover)) / (log(high_turnover) - log(low_turnover))
            return round(low_score + ratio * (high_score - low_score), 1)
    return 100.0


def liquidity_profile(
    candles: list[StockCandle],
    symbol: str,
    market: str = "",
    *,
    bars: int = 60,
    rates: dict[str, float] | None = None,
) -> dict[str, object]:
    """Return the liquidity score plus the raw numbers it was derived from."""
    currency = trading_currency(symbol, market)
    turnover = median_turnover(candles, bars)
    turnover_usd = to_usd(turnover, currency, rates)
    if turnover_usd is None:
        return {
            "score": 0.0,
            "turnover": round(turnover, 2),
            "turnover_usd": None,
            "currency": currency,
            "bars": bars,
            "verified": False,
            "note": f"ไม่มีอัตราแลกเปลี่ยน {currency} จึงประเมินสภาพคล่องเป็น USD ไม่ได้",
        }
    return {
        "score": _score_from_usd(turnover_usd),
        "turnover": round(turnover, 2),
        "turnover_usd": round(turnover_usd, 2),
        "currency": currency,
        "bars": bars,
        "verified": True,
        "note": "มูลค่าซื้อขายกลาง (median) ต่อวันแปลงเป็น USD",
    }


def liquidity_score(
    candles: list[StockCandle],
    symbol: str,
    market: str = "",
    *,
    bars: int = 60,
    rates: dict[str, float] | None = None,
) -> float:
    return float(liquidity_profile(candles, symbol, market, bars=bars, rates=rates)["score"])
