from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any

from .data_io import load_market_data
from .models import ScanCriteria, StockCandle
from .patterns import detect_patterns
from .timeframes import aggregate_candles, normalize_timeframe


DEFAULT_HORIZONS = (5, 10, 20)
DEFAULT_COST_BPS = 30.0
# Detectors never look back further than ~180 bars, so scoring each historical
# bar against the full 5-year history only repeats work. A bounded window keeps
# the study finishable while leaving the long moving averages usable.
HISTORY_WINDOW = 420


def _eligible(snapshot: Any, criteria: ScanCriteria) -> bool:
    if criteria.market != "ALL" and snapshot.market.upper() != criteria.market.upper():
        return False
    if criteria.universe == "ALL":
        return True
    groups = {item.strip().upper() for item in snapshot.index_groups.split("|") if item.strip()}
    return criteria.universe.upper() in groups


def _forward_stats(
    candles: list[StockCandle],
    index: int,
    horizon: int,
    direction: int,
    cost_bps: float,
) -> dict[str, float] | None:
    """Return the outcome of holding for ``horizon`` bars, net of round-trip cost."""
    entry = candles[index].close
    exit_index = index + horizon
    if not entry or exit_index >= len(candles):
        return None
    gross = (candles[exit_index].close / entry - 1) * 100 * direction
    forward = candles[index + 1 : exit_index + 1]
    # Drawdown is measured against the intrabar extreme a stop would actually
    # have traded through, not the friendlier closing price.
    adverse_prices = [bar.low if direction > 0 else bar.high for bar in forward]
    adverse = min((price / entry - 1) * 100 * direction for price in adverse_prices) if adverse_prices else 0.0
    favourable_prices = [bar.high if direction > 0 else bar.low for bar in forward]
    favourable = max((price / entry - 1) * 100 * direction for price in favourable_prices) if favourable_prices else 0.0
    return {
        "return_pct": round(gross, 3),
        "return_pct_net": round(gross - cost_bps / 100, 3),
        "max_drawdown_pct": round(adverse, 3),
        "max_favourable_pct": round(favourable, 3),
    }


def _aggregate(rows: list[dict[str, Any]], horizons: tuple[int, ...]) -> dict[str, Any]:
    output: dict[str, Any] = {"signals": len(rows)}
    for horizon in horizons:
        key = f"h{horizon}"
        net = [row["horizons"][key]["return_pct_net"] for row in rows if key in row["horizons"]]
        drawdown = [row["horizons"][key]["max_drawdown_pct"] for row in rows if key in row["horizons"]]
        if not net:
            output[key] = None
            continue
        output[key] = {
            "samples": len(net),
            "hit_rate_pct": round(sum(value > 0 for value in net) / len(net) * 100, 2),
            "average_return_pct_net": round(sum(net) / len(net), 3),
            "median_return_pct_net": round(median(net), 3),
            "best_pct": round(max(net), 3),
            "worst_pct": round(min(net), 3),
            "average_max_drawdown_pct": round(sum(drawdown) / len(drawdown), 3) if drawdown else None,
            "worst_max_drawdown_pct": round(min(drawdown), 3) if drawdown else None,
        }
    return output


def _grouped_summary(
    events: list[dict[str, Any]],
    key: str,
    horizons: tuple[int, ...],
    minimum_samples: int = 20,
) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        buckets[str(event.get(key) or "-")].append(event)
    summary = []
    for name, rows in sorted(buckets.items()):
        entry = {key: name, **_aggregate(rows, horizons)}
        entry["reliable"] = len(rows) >= minimum_samples
        if not entry["reliable"]:
            entry["note"] = f"ตัวอย่างน้อยกว่า {minimum_samples} สัญญาณ ยังสรุปไม่ได้"
        summary.append(entry)
    return sorted(summary, key=lambda item: item["signals"], reverse=True)


def _baseline_rows(
    candles: list[StockCandle],
    start_bars: int,
    horizons: tuple[int, ...],
    cost_bps: float,
    step: int,
) -> list[dict[str, Any]]:
    """Forward returns from entering on an arbitrary bar, same symbol and window.

    Without this a 64% hit rate looks like an edge when it may only be the
    market drifting up over the holding period.
    """
    longest = max(horizons)
    rows: list[dict[str, Any]] = []
    for index in range(start_bars, len(candles) - longest, max(1, step)):
        by_horizon: dict[str, dict[str, float]] = {}
        for horizon in horizons:
            stats = _forward_stats(candles, index, horizon, 1, cost_bps)
            if stats:
                by_horizon[f"h{horizon}"] = stats
        if by_horizon:
            rows.append({"horizons": by_horizon})
    return rows


def run_event_study(
    criteria: ScanCriteria,
    *,
    holding_bars: int | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    cooldown_bars: int = 20,
    cost_bps: float = DEFAULT_COST_BPS,
    max_symbols: int | None = None,
    baseline_step: int = 10,
    market_data_path: str | None = None,
    fundamentals_path: str | None = None,
) -> dict[str, Any]:
    """Measure forward returns after historical pattern signals.

    This is an event study, not a portfolio backtest: it does not size positions,
    cap concurrent exposure, or compound. It answers one question - after this
    pattern fired, what happened next, after costs.
    """
    timeframe = normalize_timeframe(criteria.timeframe)
    horizons = tuple(sorted({int(value) for value in (horizons or DEFAULT_HORIZONS) if int(value) > 0}))
    if holding_bars:
        horizons = tuple(sorted(set(horizons) | {int(holding_bars)}))
    longest = max(horizons)
    candles_by_symbol, fundamentals = load_market_data(market_data_path, fundamentals_path)
    events: list[dict[str, Any]] = []
    baseline: list[dict[str, Any]] = []
    start_bars = 24 if timeframe == "M" else 90
    symbols_scanned = 0
    skipped_short_history = 0

    for symbol, daily_candles in candles_by_symbol.items():
        snapshot = fundamentals.get(symbol)
        if snapshot is None or not _eligible(snapshot, criteria):
            continue
        if max_symbols is not None and symbols_scanned >= max_symbols:
            break
        candles = aggregate_candles(daily_candles, timeframe)
        if len(candles) < start_bars + longest + 1:
            skipped_short_history += 1
            continue
        symbols_scanned += 1
        baseline.extend(_baseline_rows(candles, start_bars, horizons, cost_bps, baseline_step))
        last_signal_index = -cooldown_bars
        for index in range(start_bars, len(candles) - longest):
            if index - last_signal_index < cooldown_bars:
                continue
            history = candles[max(0, index + 1 - HISTORY_WINDOW) : index + 1]
            hits = detect_patterns(history, criteria.patterns, timeframe)
            if not hits:
                continue
            hit = hits[0]
            direction = -1 if hit.side == "SELL" else 1
            by_horizon: dict[str, dict[str, float]] = {}
            for horizon in horizons:
                stats = _forward_stats(candles, index, horizon, direction, cost_bps)
                if stats:
                    by_horizon[f"h{horizon}"] = stats
            if not by_horizon:
                continue
            events.append(
                {
                    "symbol": symbol,
                    "market": snapshot.market,
                    "pattern": hit.name,
                    "side": hit.side,
                    "timeframe": timeframe,
                    "signal_date": candles[index].date.isoformat(),
                    "horizons": by_horizon,
                }
            )
            last_signal_index = index

    baseline_summary = _aggregate(baseline, horizons)
    by_pattern = _grouped_summary(events, "pattern", horizons)
    for row in by_pattern:
        row["edge_vs_baseline"] = _edge(row, baseline_summary, horizons)
    overall = _aggregate(events, horizons)
    return {
        "method": (
            "Historical event study. Does not model portfolio sizing, position overlap, "
            "or compounding. Returns are net of a round-trip cost assumption only. "
            "Baseline is an arbitrary long entry on the same symbols and window, so a "
            "pattern only has an edge when it beats that number."
        ),
        "criteria": criteria.__dict__,
        "timeframe": timeframe,
        "horizons": list(horizons),
        "cost_bps": cost_bps,
        "cooldown_bars": cooldown_bars,
        "symbols_scanned": symbols_scanned,
        "symbols_skipped_short_history": skipped_short_history,
        "signals": len(events),
        "insufficient_history": symbols_scanned == 0,
        "baseline": baseline_summary,
        "overall": overall,
        "edge_vs_baseline": _edge({**overall}, baseline_summary, horizons),
        "by_pattern": by_pattern,
        "by_market": _grouped_summary(events, "market", horizons),
        "events": events,
    }


def _edge(
    row: dict[str, Any],
    baseline: dict[str, Any],
    horizons: tuple[int, ...],
) -> dict[str, Any]:
    """How much the signal adds over simply being long the same names."""
    output: dict[str, Any] = {}
    for horizon in horizons:
        key = f"h{horizon}"
        signal_stats = row.get(key)
        base_stats = baseline.get(key)
        if not signal_stats or not base_stats:
            output[key] = None
            continue
        output[key] = {
            "return_edge_pp": round(
                signal_stats["average_return_pct_net"] - base_stats["average_return_pct_net"], 3
            ),
            "hit_rate_edge_pp": round(signal_stats["hit_rate_pct"] - base_stats["hit_rate_pct"], 2),
        }
    return output
