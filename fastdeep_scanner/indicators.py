from __future__ import annotations

from statistics import mean

from .models import StockCandle


def average(values: list[float], fallback: float = 0.0) -> float:
    clean = [value for value in values if value is not None]
    return mean(clean) if clean else fallback


def closes(candles: list[StockCandle]) -> list[float]:
    return [candle.close for candle in candles]


def highs(candles: list[StockCandle]) -> list[float]:
    return [candle.high for candle in candles]


def lows(candles: list[StockCandle]) -> list[float]:
    return [candle.low for candle in candles]


def volumes(candles: list[StockCandle]) -> list[float]:
    return [candle.volume for candle in candles]


def sma(values: list[float], bars: int) -> float:
    if not values:
        return 0.0
    window = values[-bars:] if len(values) >= bars else values
    return average(window, values[-1])


def ema_series(values: list[float], bars: int) -> list[float]:
    if not values:
        return []
    multiplier = 2 / (bars + 1)
    series = [values[0]]
    for value in values[1:]:
        series.append((value - series[-1]) * multiplier + series[-1])
    return series


def ema(values: list[float], bars: int) -> float:
    series = ema_series(values, bars)
    return series[-1] if series else 0.0


def true_range(current: StockCandle, previous_close: float | None) -> float:
    if previous_close is None:
        return current.high - current.low
    return max(
        current.high - current.low,
        abs(current.high - previous_close),
        abs(current.low - previous_close),
    )


def atr(candles: list[StockCandle], bars: int = 14) -> float:
    if not candles:
        return 0.0
    ranges: list[float] = []
    start = max(0, len(candles) - bars)
    for idx in range(start, len(candles)):
        previous_close = candles[idx - 1].close if idx > 0 else None
        ranges.append(true_range(candles[idx], previous_close))
    return average(ranges, candles[-1].high - candles[-1].low)


def pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0
    return (current - previous) / previous * 100


def volume_ratio(candles: list[StockCandle], bars: int = 20) -> float:
    if len(candles) < 2:
        return 1.0
    history = [candle.volume for candle in candles[-bars - 1 : -1]]
    baseline = average(history, candles[-1].volume)
    return candles[-1].volume / baseline if baseline else 1.0


def rolling_high(candles: list[StockCandle], bars: int, exclude_latest: bool = True) -> float:
    window = candles[-bars - 1 : -1] if exclude_latest else candles[-bars:]
    if not window:
        return candles[-1].high if candles else 0.0
    return max(candle.high for candle in window)


def rolling_low(candles: list[StockCandle], bars: int, exclude_latest: bool = True) -> float:
    window = candles[-bars - 1 : -1] if exclude_latest else candles[-bars:]
    if not window:
        return candles[-1].low if candles else 0.0
    return min(candle.low for candle in window)


def slope_pct(values: list[float], bars: int = 20) -> float:
    if len(values) <= bars:
        return 0.0
    return pct_change(values[-1], values[-bars])


def local_lows(candles: list[StockCandle], lookback: int = 120, radius: int = 4) -> list[tuple[int, float]]:
    start = max(radius, len(candles) - lookback)
    pivots: list[tuple[int, float]] = []
    for idx in range(start, len(candles) - radius):
        value = candles[idx].low
        neighborhood = candles[idx - radius : idx + radius + 1]
        if value == min(candle.low for candle in neighborhood):
            pivots.append((idx, value))
    return pivots


def local_highs(candles: list[StockCandle], lookback: int = 120, radius: int = 4) -> list[tuple[int, float]]:
    start = max(radius, len(candles) - lookback)
    pivots: list[tuple[int, float]] = []
    for idx in range(start, len(candles) - radius):
        value = candles[idx].high
        neighborhood = candles[idx - radius : idx + radius + 1]
        if value == max(candle.high for candle in neighborhood):
            pivots.append((idx, value))
    return pivots
