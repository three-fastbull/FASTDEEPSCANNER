from __future__ import annotations

import math
import random
from datetime import date, timedelta

from .models import FundamentalSnapshot, StockCandle


SAMPLE_FUNDAMENTALS = [
    FundamentalSnapshot("NVDA", "NVIDIA", "US", "Semiconductors", 76.0, 42.0, 0.31, 58.0, 84.0, 73.0, 49.0, 34.0, 28.0, 0.0, 23.0, 96.0, "wide", "leader", "AI compute platform leader"),
    FundamentalSnapshot("MSFT", "Microsoft", "US", "Software", 36.0, 18.0, 0.42, 16.0, 20.0, 69.0, 36.0, 31.0, 11.0, 0.8, 14.0, 98.0, "wide", "leader", "Cloud and AI operating leverage"),
    FundamentalSnapshot("AAPL", "Apple", "US", "Consumer Technology", 62.0, 25.0, 1.45, 5.0, 4.0, 45.0, 26.0, 28.0, 36.0, 0.5, 8.0, 97.0, "wide", "beneficiary", "High quality but slower growth"),
    FundamentalSnapshot("AMD", "Advanced Micro Devices", "US", "Semiconductors", 12.0, 5.8, 0.09, 24.0, 33.0, 51.0, 8.0, 42.0, 4.2, 0.0, 28.0, 86.0, "medium", "beneficiary", "AI accelerator upside with execution risk"),
    FundamentalSnapshot("CPALL.BK", "CP All", "TH", "Commerce", 18.0, 6.2, 1.1, 11.0, 18.0, 22.0, 4.2, 25.0, 5.3, 1.2, 24.0, 83.0, "strong", "automation", "Convenience store scale and cash flow"),
    FundamentalSnapshot("AOT.BK", "Airports of Thailand", "TH", "Transport", 14.0, 9.0, 0.38, 18.0, 38.0, 48.0, 22.0, 38.0, 6.4, 1.0, 18.0, 88.0, "wide", "automation", "Tourism recovery and monopoly asset"),
    FundamentalSnapshot("ADVANC.BK", "Advanced Info Service", "TH", "Digital Infrastructure", 32.0, 12.5, 1.35, 8.0, 10.0, 33.0, 18.0, 21.0, 7.9, 3.7, 12.0, 91.0, "strong", "beneficiary", "Telecom cash flow and data demand"),
    FundamentalSnapshot("BBL.BK", "Bangkok Bank", "TH", "Banking", 9.0, 1.1, 7.9, 6.0, 9.0, 0.0, 18.0, 8.0, 0.72, 4.1, 16.0, 78.0, "medium", "neutral", "Low valuation cyclical bank"),
    FundamentalSnapshot("PTT.BK", "PTT", "TH", "Energy", 8.5, 3.0, 1.05, -2.0, -8.0, 13.0, 5.0, 11.0, 0.86, 5.0, 6.0, 84.0, "medium", "neutral", "Energy cycle and state enterprise profile"),
]


SCENARIOS = {
    "NVDA": ("breakout", 840.0),
    "MSFT": ("healthy_uptrend", 410.0),
    "AAPL": ("sideways", 190.0),
    "AMD": ("breakout", 155.0),
    "CPALL.BK": ("double_bottom", 54.0),
    "AOT.BK": ("cup_handle", 62.0),
    "ADVANC.BK": ("retest", 214.0),
    "BBL.BK": ("healthy_uptrend", 142.0),
    "PTT.BK": ("head_shoulders", 36.0),
}


def _business_dates(days: int) -> list[date]:
    current = date.today()
    dates: list[date] = []
    while len(dates) < days:
        if current.weekday() < 5:
            dates.append(current)
        current -= timedelta(days=1)
    return list(reversed(dates))


def _interpolate(days: int, anchors: list[tuple[int, float]]) -> list[float]:
    anchors = sorted(anchors)
    prices: list[float] = []
    anchor_idx = 0
    for idx in range(days):
        while anchor_idx < len(anchors) - 2 and idx > anchors[anchor_idx + 1][0]:
            anchor_idx += 1
        left_idx, left_price = anchors[anchor_idx]
        right_idx, right_price = anchors[min(anchor_idx + 1, len(anchors) - 1)]
        span = max(1, right_idx - left_idx)
        progress = max(0.0, min(1.0, (idx - left_idx) / span))
        prices.append(left_price + (right_price - left_price) * progress)
    return prices


def _anchors(scenario: str, start: float, days: int) -> list[tuple[int, float]]:
    end = days - 1
    if scenario == "breakout":
        return [(0, start), (150, start * 1.12), (220, start * 1.24), (236, start * 1.21), (end, start * 1.39)]
    if scenario == "retest":
        return [(0, start), (150, start * 1.02), (210, start * 1.14), (224, start * 1.28), (234, start * 1.16), (end, start * 1.24)]
    if scenario == "double_bottom":
        return [(0, start), (65, start * 1.08), (128, start * 0.78), (168, start * 1.05), (205, start * 0.80), (230, start * 1.04), (end, start * 1.14)]
    if scenario == "cup_handle":
        return [(0, start * 1.06), (38, start * 1.10), (108, start * 0.74), (172, start * 1.02), (213, start * 1.12), (229, start * 1.01), (end, start * 1.17)]
    if scenario == "head_shoulders":
        return [(0, start), (120, start * 1.10), (150, start * 1.33), (172, start * 1.02), (196, start * 1.55), (218, start * 1.04), (233, start * 1.29), (end, start * 0.96)]
    if scenario == "healthy_uptrend":
        return [(0, start), (80, start * 1.07), (150, start * 1.17), (215, start * 1.21), (end, start * 1.27)]
    return [(0, start), (120, start * 1.03), (end, start * 1.01)]


def generate_price_history(days: int = 240) -> dict[str, list[StockCandle]]:
    dates = _business_dates(days)
    market: dict[str, list[StockCandle]] = {}
    for symbol, (scenario, start) in SCENARIOS.items():
        rng = random.Random(symbol)
        base_prices = _interpolate(days, _anchors(scenario, start, days))
        candles: list[StockCandle] = []
        previous_close = base_prices[0]
        base_volume = 1_000_000 if symbol.endswith(".BK") else 4_500_000
        for idx, base in enumerate(base_prices):
            wave = math.sin(idx / 5.5) * 0.006 + math.sin(idx / 17.0) * 0.011
            noise = rng.uniform(-0.004, 0.004)
            close = max(0.01, base * (1 + wave + noise))
            if idx == days - 1 and scenario in {"breakout", "cup_handle", "double_bottom"}:
                close = max(close, max(item.high for item in candles[-60:]) * 1.018 if candles else close)
            if idx == days - 1 and scenario == "head_shoulders":
                close = min(close, min(item.low for item in candles[-65:]) * 0.985 if candles else close)
            open_price = previous_close * (1 + rng.uniform(-0.006, 0.006))
            spread = max(close * rng.uniform(0.006, 0.018), close * 0.003)
            high = max(open_price, close) + spread
            low = min(open_price, close) - spread
            volume_wave = 1 + math.sin(idx / 11.0) * 0.16 + rng.uniform(-0.10, 0.14)
            volume = base_volume * max(0.45, volume_wave)
            if idx > days - 6 and scenario in {"breakout", "double_bottom", "cup_handle"}:
                volume *= 1.75
            if idx > days - 8 and scenario == "head_shoulders":
                volume *= 1.45
            candles.append(
                StockCandle(
                    date=dates[idx],
                    symbol=symbol,
                    open=round(open_price, 4),
                    high=round(high, 4),
                    low=round(low, 4),
                    close=round(close, 4),
                    volume=round(volume, 2),
                )
            )
            previous_close = close
        market[symbol] = candles
    return market


def fundamentals_by_symbol() -> dict[str, FundamentalSnapshot]:
    return {item.symbol: item for item in SAMPLE_FUNDAMENTALS}
