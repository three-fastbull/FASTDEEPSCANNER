from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from .models import StockCandle


SUPPORTED_TIMEFRAMES = {"D", "W", "M"}


def normalize_timeframe(value: str) -> str:
    timeframe = (value or "D").upper()
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe: {value}")
    return timeframe


def period_key(value: date, timeframe: str) -> tuple[int, int]:
    if timeframe == "W":
        iso = value.isocalendar()
        return iso.year, iso.week
    return value.year, value.month


def _period_key(candle: StockCandle, timeframe: str) -> tuple[int, int]:
    return period_key(candle.date, timeframe)


def aggregate_candles(
    candles: Iterable[StockCandle],
    timeframe: str,
    *,
    as_of: date | None = None,
    drop_incomplete: bool = True,
) -> list[StockCandle]:
    """Aggregate daily OHLCV into weekly or monthly bars.

    The final bar is dropped while its week or month is still trading, so a
    three-day stub never gets scored as a finished weekly candle - the same rule
    the daily scanner applies when it refuses to read today's intraday bar.
    """
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

    if drop_incomplete and aggregated:
        reference = as_of or date.today()
        if _period_key(aggregated[-1], timeframe) == period_key(reference, timeframe):
            aggregated.pop()
    return aggregated
