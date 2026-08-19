from __future__ import annotations

from .models import PatternHit, RiskPlan, StockCandle
from .patterns import atr_value, support_resistance


def build_risk_plan(candles: list[StockCandle], patterns: list[PatternHit]) -> RiskPlan:
    latest = candles[-1]
    current_atr = max(atr_value(candles), latest.close * 0.015)
    support, resistance = support_resistance(candles)
    bearish = any(pattern.side == "SELL" for pattern in patterns)
    entry = latest.close

    if bearish:
        stop = min(max(resistance, entry + current_atr * 1.2), entry + current_atr * 3.0)
        risk = max(entry - support, current_atr)
        targets = [
            max(0.01, support),
            max(0.01, entry - risk * 1.5),
            max(0.01, entry - risk * 2.2),
        ]
        targets = sorted(targets, reverse=True)
        return RiskPlan(
            bias="Risk-off / avoid long",
            entry=entry,
            stop=stop,
            targets=targets,
            reward_risk=3.0,
            invalidation="Bearish pattern is invalid if price reclaims the right shoulder or resistance.",
            sizing_note="Use as a reject/hedge signal until fundamentals and structure improve.",
        )

    stop = min(support, entry - current_atr * 1.4)
    risk = max(entry - stop, current_atr)
    first_target = max(resistance, entry + risk * 1.5)
    targets = sorted([first_target, entry + risk * 2.2, entry + risk * 3.0])
    return RiskPlan(
        bias="Long candidate",
        entry=entry,
        stop=stop,
        targets=targets,
        reward_risk=(targets[-1] - entry) / risk if risk else 0.0,
        invalidation="Exit the idea if price breaks back below support/SW structure with volume.",
        sizing_note="Paper trade first; real size should be capped by portfolio risk per trade.",
    )
