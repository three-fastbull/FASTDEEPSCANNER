from __future__ import annotations

from .models import PatternHit, RiskPlan, StockCandle
from .patterns import atr_value, support_resistance


# A stop has to sit outside the noise but still inside a loss the book can take.
# Structure decides where it goes between those two bounds.
MINIMUM_ATR_MULTIPLE = 1.4
MAXIMUM_ATR_MULTIPLE = 3.0
WIDE_RISK_PCT = 12.0


def build_risk_plan(candles: list[StockCandle], patterns: list[PatternHit]) -> RiskPlan:
    latest = candles[-1]
    current_atr = max(atr_value(candles), latest.close * 0.015)
    support, resistance = support_resistance(candles)
    bearish = any(pattern.side == "SELL" for pattern in patterns)
    entry = latest.close

    if bearish:
        stop = min(
            max(resistance, entry + current_atr * MINIMUM_ATR_MULTIPLE),
            entry + current_atr * MAXIMUM_ATR_MULTIPLE,
        )
        risk = max(stop - entry, current_atr)
        targets = sorted(
            [
                max(0.01, support),
                max(0.01, entry - risk * 1.5),
                max(0.01, entry - risk * 2.2),
            ],
            reverse=True,
        )
        risk_pct = risk / entry * 100 if entry else 0.0
        return RiskPlan(
            bias="Risk-off / avoid long",
            entry=entry,
            stop=stop,
            targets=targets,
            reward_risk=3.0,
            risk_pct=risk_pct,
            invalidation="Bearish pattern is invalid if price reclaims the right shoulder or resistance.",
            sizing_note="Use as a reject/hedge signal until fundamentals and structure improve.",
        )

    # Prefer the swing low, but never further out than the volatility cap - an
    # entry whose only valid stop is 25% away is not a tradable plan.
    volatility_floor = entry - current_atr * MINIMUM_ATR_MULTIPLE
    volatility_cap = entry - current_atr * MAXIMUM_ATR_MULTIPLE
    stop = min(volatility_floor, max(support, volatility_cap))
    risk = max(entry - stop, current_atr * 0.5)
    risk_pct = risk / entry * 100 if entry else 0.0
    first_target = max(resistance, entry + risk * 1.5)
    targets = sorted([first_target, entry + risk * 2.2, entry + risk * 3.0])
    sizing_note = "Paper trade first; real size should be capped by portfolio risk per trade."
    if risk_pct > WIDE_RISK_PCT:
        sizing_note = (
            f"ความเสี่ยงต่อไม้กว้างถึง {risk_pct:.1f}% ของราคาเข้า "
            "ต้องลดขนาดไม้ลงตามสัดส่วน หรือรอจุดเข้าที่ใกล้แนวรับกว่านี้"
        )
    return RiskPlan(
        bias="Long candidate",
        entry=entry,
        stop=stop,
        targets=targets,
        reward_risk=(targets[-1] - entry) / risk if risk else 0.0,
        risk_pct=risk_pct,
        invalidation="Exit the idea if price breaks back below support/SW structure with volume.",
        sizing_note=sizing_note,
    )
