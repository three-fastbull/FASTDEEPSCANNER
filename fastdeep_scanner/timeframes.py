from __future__ import annotations

from collections.abc import Iterable

from .models import StockCandle


SUPPORTED_TIMEFRAMES = {"D", "W", "M"}


def normalize_timeframe(value: str) -> str:
    timeframe = (value or "D").upper()
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe: {value}")
    return timeframe


def _period_key(candle: StockCandle, timeframe: str) -> tuple[int, int]:
    if timeframe == "W":
        iso = candle.date.isocalendar()
        return iso.year, iso.week
    return candle.date.year, candle.date.month


def aggregate_candles(candles: Iterable[StockCandle], timeframe: str) -> list[StockCandle]:
    """Aggregate daily OHLCV into complete chronological weekly or monthly bars."""
    timeframe = normalize_timeframe(timeframe)
    ordered = sorted(candles, key=lambda item: item.date)
    if timeframe == "D":
        return ordered

    aggregated: list[StockCandle] = []
    current_key: tuple[int, int] | None = None
    current: StockCandle | None = None
    for candle in ordered:
        key = _period_key(candle, timeframe)
        if key != current_key:
            if current is not None:
                aggregated.append(current)
            current_key = key
            current = candle
            continue
        assert current is not None
        current = StockCandle(
            date=candle.date,
            symbol=candle.symbol,
            open=current.open,
            high=max(current.high, candle.high),
            low=min(current.low, candle.low),
            close=candle.close,
            volume=current.volume + candle.volume,
        )
    if current is not None:
        aggregated.append(current)
    return aggregated
