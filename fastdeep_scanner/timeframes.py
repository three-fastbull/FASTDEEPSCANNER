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

    # Carry the running period in plain locals and build one StockCandle when it
    # closes. Rebuilding the dataclass on every daily bar meant 1.75 million
    # allocations across the universe, which was the whole cost of a monthly scan.
    aggregated: list[StockCandle] = []
    current_key: tuple[int, int] | None = None
    symbol = ""
    period_open = high = low = last_close = 0.0
    volume = 0.0
    last_date: date | None = None

    for candle in ordered:
        key = _period_key(candle, timeframe)
        if key != current_key:
            if last_date is not None:
                aggregated.append(
                    StockCandle(
                        date=last_date,
                        symbol=symbol,
                        open=period_open,
                        high=high,
                        low=low,
                        close=last_close,
                        volume=volume,
                    )
                )
            current_key = key
            symbol = candle.symbol
            period_open = candle.open
            high = candle.high
            low = candle.low
            volume = 0.0
        else:
            if candle.high > high:
                high = candle.high
            if candle.low < low:
                low = candle.low
        last_close = candle.close
        last_date = candle.date
        volume += candle.volume

    if last_date is not None:
        aggregated.append(
            StockCandle(
                date=last_date,
                symbol=symbol,
                open=period_open,
                high=high,
                low=low,
                close=last_close,
                volume=volume,
            )
        )

    if drop_incomplete and aggregated:
        reference = as_of or date.today()
        if _period_key(aggregated[-1], timeframe) == period_key(reference, timeframe):
            aggregated.pop()
    return aggregated
