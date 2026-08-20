from __future__ import annotations

from .indicators import (
    atr,
    closes,
    ema,
    highs,
    local_highs,
    local_lows,
    lows,
    pct_change,
    rolling_high,
    rolling_low,
    slope_pct,
    volume_ratio,
)
from .models import PatternHit, StockCandle
from .timeframes import normalize_timeframe


PATTERN_LABELS = {
    "breakout": "Breakout",
    "retest": "Breakout Retest",
    "cup_handle": "Cup & Handle",
    "double_bottom": "Double Bottom",
    "head_shoulders": "Head & Shoulders",
}


def market_phase(candles: list[StockCandle]) -> str:
    values = closes(candles)
    if len(values) < 60:
        return "UNKNOWN"
    ema20 = ema(values, 20)
    ema50 = ema(values, 50)
    ema200 = ema(values, 200)
    close = values[-1]
    ema50_slope = slope_pct(values, 30)
    compression = abs(ema20 - ema50) / close if close else 0.0
    if close > ema50 > ema200 and ema50_slope > 2.0:
        return "RUN"
    if close < ema50 < ema200 and ema50_slope < -2.0:
        return "DOWN"
    if compression < 0.035:
        return "SW"
    return "TRANSITION"


def _bars(value: int, timeframe: str) -> int:
    return max(3, round(value * (0.28 if timeframe == "M" else 1.0)))


def detect_breakout(candles: list[StockCandle], timeframe: str = "D") -> PatternHit | None:
    timeframe = normalize_timeframe(timeframe)
    if len(candles) < _bars(90, timeframe):
        return None
    close = candles[-1].close
    previous_high = rolling_high(candles, _bars(60, timeframe), exclude_latest=True)
    vol_ratio = volume_ratio(candles, _bars(20, timeframe))
    values = closes(candles)
    ema50 = ema(values, 50)
    ema200 = ema(values, 200)
    breakout_pct = pct_change(close, previous_high)
    if close <= previous_high * 1.006:
        return None
    if close <= ema50:
        return None
    trend_bonus = 8 if close > ema200 else 2
    volume_bonus = min(16, max(0, (vol_ratio - 1.0) * 18))
    score = min(95, 58 + breakout_pct * 1.6 + trend_bonus + volume_bonus)
    reasons = [
        f"Close broke 60-day resistance at {previous_high:.2f}",
        f"Volume is {vol_ratio:.2f}x the 20-day average",
        "Price is above EMA50",
    ]
    if close > ema200:
        reasons.append("Price is above EMA200")
    return PatternHit(
        name="breakout",
        label=PATTERN_LABELS["breakout"],
        side="BUY",
        score=score,
        confidence=min(96, 62 + breakout_pct + volume_bonus),
        level=previous_high,
        reasons=reasons,
    )


def detect_retest(candles: list[StockCandle], timeframe: str = "D") -> PatternHit | None:
    timeframe = normalize_timeframe(timeframe)
    if len(candles) < _bars(110, timeframe):
        return None
    base_bars = _bars(90, timeframe)
    recent_bars = _bars(24, timeframe)
    base_window = candles[-base_bars:-recent_bars]
    recent_window = candles[-recent_bars:-1]
    if not base_window or not recent_window:
        return None
    resistance = max(candle.high for candle in base_window)
    broke_recently = any(candle.close > resistance * 1.008 for candle in recent_window)
    latest = candles[-1]
    near_level = latest.low <= resistance * 1.035 and latest.close >= resistance * 0.985
    bounce = latest.close > candles[-2].close and latest.close > resistance
    if not (broke_recently and near_level and bounce):
        return None
    vol_ratio = volume_ratio(candles, _bars(20, timeframe))
    support_quality = max(0, 1 - abs(latest.close - resistance) / max(resistance, 0.01))
    score = min(92, 60 + support_quality * 14 + min(13, vol_ratio * 5))
    return PatternHit(
        name="retest",
        label=PATTERN_LABELS["retest"],
        side="BUY",
        score=score,
        confidence=min(93, 60 + support_quality * 20 + min(10, vol_ratio * 4)),
        level=resistance,
        reasons=[
            f"Prior resistance near {resistance:.2f} became support",
            "Latest candle closed back above the retest level",
            f"Volume confirmation is {vol_ratio:.2f}x",
        ],
    )


def detect_double_bottom(candles: list[StockCandle], timeframe: str = "D") -> PatternHit | None:
    timeframe = normalize_timeframe(timeframe)
    if len(candles) < _bars(130, timeframe):
        return None
    pivots = local_lows(candles, lookback=_bars(120, timeframe), radius=_bars(5, timeframe))
    latest = candles[-1]
    candidates: list[tuple[int, float, int, float]] = []
    for left_idx, left_low in pivots:
        for right_idx, right_low in pivots:
            if right_idx - left_idx < _bars(18, timeframe):
                continue
            similarity = abs(left_low - right_low) / max(left_low, right_low)
            if similarity <= 0.055 and right_idx > left_idx:
                candidates.append((left_idx, left_low, right_idx, right_low))
    if not candidates:
        return None
    left_idx, left_low, right_idx, right_low = candidates[-1]
    neckline = max(candle.high for candle in candles[left_idx:right_idx + 1])
    if latest.close <= neckline * 1.005:
        return None
    depth = pct_change(neckline, min(left_low, right_low))
    vol_ratio = volume_ratio(candles, _bars(20, timeframe))
    score = min(94, 61 + depth * 0.7 + min(12, vol_ratio * 4))
    return PatternHit(
        name="double_bottom",
        label=PATTERN_LABELS["double_bottom"],
        side="BUY",
        score=score,
        confidence=min(94, 60 + depth * 0.65 + min(10, vol_ratio * 3)),
        level=neckline,
        reasons=[
            f"Two lows formed around {((left_low + right_low) / 2):.2f}",
            f"Neckline broke above {neckline:.2f}",
            f"Recovery depth is {depth:.1f}%",
        ],
    )


def detect_cup_handle(candles: list[StockCandle], timeframe: str = "D") -> PatternHit | None:
    timeframe = normalize_timeframe(timeframe)
    if len(candles) < _bars(180, timeframe):
        return None
    window = candles[-_bars(170, timeframe):]
    left_end = _bars(45, timeframe)
    bowl_end = _bars(125, timeframe)
    right_end = _bars(150, timeframe)
    left = window[:left_end]
    bowl = window[left_end:bowl_end]
    right = window[bowl_end:right_end]
    handle = window[right_end:-1]
    latest = candles[-1]
    if not (left and bowl and right and handle):
        return None
    left_high = max(candle.high for candle in left)
    bowl_low = min(candle.low for candle in bowl)
    right_high = max(candle.high for candle in right)
    handle_high = max(candle.high for candle in handle)
    handle_low = min(candle.low for candle in handle)
    depth = (left_high - bowl_low) / left_high if left_high else 0.0
    right_recovery = right_high / left_high if left_high else 0.0
    handle_pullback = (handle_high - handle_low) / handle_high if handle_high else 0.0
    broke_handle = latest.close > handle_high * 1.005
    valid_shape = 0.12 <= depth <= 0.42 and 0.86 <= right_recovery <= 1.25
    valid_handle = 0.025 <= handle_pullback <= 0.18
    if not (valid_shape and valid_handle and broke_handle):
        return None
    vol_ratio = volume_ratio(candles, _bars(20, timeframe))
    score = min(96, 64 + depth * 55 + min(12, vol_ratio * 4))
    return PatternHit(
        name="cup_handle",
        label=PATTERN_LABELS["cup_handle"],
        side="BUY",
        score=score,
        confidence=min(95, 62 + depth * 50 + min(10, vol_ratio * 3)),
        level=handle_high,
        reasons=[
            f"Cup depth is {depth:.1%}",
            f"Handle pullback is {handle_pullback:.1%}",
            f"Price broke handle resistance at {handle_high:.2f}",
        ],
    )


def detect_head_shoulders(candles: list[StockCandle], timeframe: str = "D") -> PatternHit | None:
    timeframe = normalize_timeframe(timeframe)
    if len(candles) < _bars(130, timeframe):
        return None
    peaks = local_highs(candles, lookback=_bars(125, timeframe), radius=_bars(4, timeframe))
    if len(peaks) < 3:
        return None
    selected: tuple[int, float, int, float, int, float] | None = None
    for first in range(len(peaks) - 2):
        l_idx, left = peaks[first]
        h_idx, head = peaks[first + 1]
        r_idx, right = peaks[first + 2]
        separated = h_idx - l_idx >= _bars(10, timeframe) and r_idx - h_idx >= _bars(10, timeframe)
        head_is_high = head > left * 1.04 and head > right * 1.04
        shoulders_match = abs(left - right) / max(left, right) <= 0.15
        if separated and head_is_high and shoulders_match:
            selected = (l_idx, left, h_idx, head, r_idx, right)
    if selected is None:
        return None
    l_idx, left, h_idx, head, r_idx, right = selected
    neckline = min(
        min(candle.low for candle in candles[l_idx:h_idx + 1]),
        min(candle.low for candle in candles[h_idx:r_idx + 1]),
    )
    latest = candles[-1]
    if latest.close >= neckline * 0.99:
        return None
    pattern_height = (head - neckline) / max(neckline, 0.01)
    score = min(91, 60 + pattern_height * 85)
    return PatternHit(
        name="head_shoulders",
        label=PATTERN_LABELS["head_shoulders"],
        side="SELL",
        score=score,
        confidence=min(91, 60 + pattern_height * 70),
        level=neckline,
        reasons=[
            f"Head peak {head:.2f} is above shoulders {left:.2f}/{right:.2f}",
            f"Price closed below neckline {neckline:.2f}",
            "Pattern is bearish and should reduce long conviction",
        ],
    )


DETECTORS = {
    "breakout": detect_breakout,
    "retest": detect_retest,
    "cup_handle": detect_cup_handle,
    "double_bottom": detect_double_bottom,
    "head_shoulders": detect_head_shoulders,
}


def detect_patterns(
    candles: list[StockCandle], selected: tuple[str, ...], timeframe: str = "D"
) -> list[PatternHit]:
    hits: list[PatternHit] = []
    for name in selected:
        detector = DETECTORS.get(name)
        if detector is None:
            continue
        hit = detector(candles, timeframe)
        if hit is not None:
            hits.append(hit)
    return sorted(hits, key=lambda item: item.score, reverse=True)


def technical_context_score(candles: list[StockCandle], hits: list[PatternHit]) -> tuple[float, list[str]]:
    if not candles:
        return 0.0, ["No price history"]
    values = closes(candles)
    last = candles[-1].close
    ema20 = ema(values, 20)
    ema50 = ema(values, 50)
    ema200 = ema(values, 200)
    score = max((hit.score for hit in hits), default=42.0)
    reasons: list[str] = []
    if last > ema20:
        score += 4
        reasons.append("Close is above EMA20")
    if last > ema50:
        score += 6
        reasons.append("Close is above EMA50")
    if last > ema200:
        score += 7
        reasons.append("Close is above EMA200")
    if volume_ratio(candles, 20) >= 1.35:
        score += 6
        reasons.append("Volume expansion confirms attention")
    if market_phase(candles) == "RUN":
        score += 5
        reasons.append("Market phase is RUN")
    if any(hit.side == "SELL" for hit in hits):
        score -= 14
        reasons.append("Bearish pattern detected")
    return min(100, max(0, score)), reasons


def support_resistance(candles: list[StockCandle]) -> tuple[float, float]:
    support = rolling_low(candles, 35, exclude_latest=False)
    resistance = rolling_high(candles, 60, exclude_latest=True)
    return support, resistance


def atr_value(candles: list[StockCandle]) -> float:
    return atr(candles, 14)


def recent_high_low(candles: list[StockCandle]) -> tuple[float, float]:
    return max(highs(candles[-30:])), min(lows(candles[-30:]))
