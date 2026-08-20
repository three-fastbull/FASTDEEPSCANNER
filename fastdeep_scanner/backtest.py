from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any

from .data_io import load_market_data
from .models import ScanCriteria
from .patterns import detect_patterns
from .timeframes import aggregate_candles, normalize_timeframe


def _eligible(symbol: str, snapshot: Any, criteria: ScanCriteria) -> bool:
    if criteria.market != "ALL" and snapshot.market.upper() != criteria.market.upper():
        return False
    if criteria.universe == "ALL":
        return True
    groups = {item.strip().upper() for item in snapshot.index_groups.split("|") if item.strip()}
    return criteria.universe.upper() in groups


def run_event_study(
    criteria: ScanCriteria,
    *,
    holding_bars: int = 20,
    cooldown_bars: int = 20,
    market_data_path: str | None = None,
    fundamentals_path: str | None = None,
) -> dict[str, Any]:
    """Measure forward returns after historical pattern signals, not a portfolio simulation."""
    timeframe = normalize_timeframe(criteria.timeframe)
    candles_by_symbol, fundamentals = load_market_data(market_data_path, fundamentals_path)
    events: list[dict[str, Any]] = []
    start_bars = 50 if timeframe == "M" else 90

    for symbol, daily_candles in candles_by_symbol.items():
        snapshot = fundamentals.get(symbol)
        if snapshot is None or not _eligible(symbol, snapshot, criteria):
            continue
        candles = aggregate_candles(daily_candles, timeframe)
        last_signal_index = -cooldown_bars
        for index in range(start_bars, len(candles) - holding_bars):
            if index - last_signal_index < cooldown_bars:
                continue
            history = candles[: index + 1]
            hits = detect_patterns(history, criteria.patterns, timeframe)
            if not hits:
                continue
            hit = hits[0]
            entry = candles[index].close
            exit_price = candles[index + holding_bars].close
            direction = -1 if hit.side == "SELL" else 1
            forward_return = (exit_price / entry - 1) * 100 * direction if entry else 0.0
            adverse_prices = [bar.close for bar in candles[index + 1 : index + holding_bars + 1]]
            adverse = (
                min((price / entry - 1) * 100 * direction for price in adverse_prices)
                if adverse_prices and entry
                else 0.0
            )
            events.append(
                {
                    "symbol": symbol,
                    "pattern": hit.name,
                    "side": hit.side,
                    "signal_date": candles[index].date.isoformat(),
                    "forward_return_pct": round(forward_return, 3),
                    "max_adverse_pct": round(adverse, 3),
                }
            )
            last_signal_index = index

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[event["pattern"]].append(event)
    summary = []
    for pattern, rows in sorted(grouped.items()):
        returns = [row["forward_return_pct"] for row in rows]
        adverse = [row["max_adverse_pct"] for row in rows]
        summary.append(
            {
                "pattern": pattern,
                "signals": len(rows),
                "hit_rate_pct": round(sum(value > 0 for value in returns) / len(returns) * 100, 2),
                "average_return_pct": round(sum(returns) / len(returns), 3),
                "median_return_pct": round(median(returns), 3),
                "best_return_pct": round(max(returns), 3),
                "worst_return_pct": round(min(returns), 3),
                "average_max_adverse_pct": round(sum(adverse) / len(adverse), 3),
            }
        )
    return {
        "method": "Historical event study. Does not model portfolio sizing, fees, slippage, or overlapping positions.",
        "criteria": criteria.__dict__,
        "holding_bars": holding_bars,
        "cooldown_bars": cooldown_bars,
        "events": events,
        "summary": summary,
    }
