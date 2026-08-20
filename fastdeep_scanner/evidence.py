"""Historical evidence gate for pattern signals.

The event study showed that most patterns do not beat simply being long the same
names over the same window - on daily bars none of them do. A grade is only
allowed to read as a buy candidate when the pattern that produced it has a
measured edge over that baseline at the timeframe being scanned.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
STUDY_DIR = ROOT / "storage"

# An edge has to clear both bars to count: enough signals to be measurable, and
# a return advantage large enough to survive costs and ordinary variance.
MINIMUM_SIGNALS = 200
MINIMUM_EDGE_PP = 0.5


def study_path(timeframe: str) -> Path:
    return STUDY_DIR / f"fastdeep_event_study_{timeframe.upper()}.json"


@lru_cache(maxsize=8)
def _load_study(timeframe: str, modified_ns: int) -> dict[str, Any]:
    path = study_path(timeframe)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    payload.pop("events", None)
    return payload


def load_study(timeframe: str) -> dict[str, Any]:
    path = study_path(timeframe)
    if not path.exists():
        return {}
    return _load_study(timeframe.upper(), path.stat().st_mtime_ns)


def pattern_edge(pattern: str, timeframe: str) -> dict[str, Any]:
    """What history says about this pattern on this timeframe, versus baseline."""
    study = load_study(timeframe)
    if not study:
        return {
            "available": False,
            "verdict": "unmeasured",
            "label": "ยังไม่มีผลทดสอบย้อนหลังของ timeframe นี้",
            "tradeable": False,
        }
    horizon_key = f"h{study['horizons'][-1]}"
    row = next((item for item in study.get("by_pattern", []) if item.get("pattern") == pattern), None)
    if not row or not row.get(horizon_key):
        return {
            "available": False,
            "verdict": "unmeasured",
            "label": f"ยังไม่มีสถิติของ {pattern} ใน timeframe นี้",
            "tradeable": False,
        }

    stats = row[horizon_key]
    edge = (row.get("edge_vs_baseline") or {}).get(horizon_key) or {}
    baseline = (study.get("baseline") or {}).get(horizon_key) or {}
    return_edge = float(edge.get("return_edge_pp") or 0.0)
    hit_edge = float(edge.get("hit_rate_edge_pp") or 0.0)
    signals = int(row.get("signals") or 0)
    horizon = int(study["horizons"][-1])

    if signals < MINIMUM_SIGNALS:
        verdict, tradeable = "insufficient", False
        label = f"ตัวอย่างเพียง {signals} สัญญาณ ยังสรุปไม่ได้"
    elif return_edge >= MINIMUM_EDGE_PP and hit_edge > 0:
        verdict, tradeable = "edge", True
        label = (
            f"ชนะค่าฐาน {return_edge:.2f} จุด และอัตราชนะสูงกว่า {hit_edge:.1f} จุด "
            f"จาก {signals} สัญญาณ (ถือ {horizon} แท่ง)"
        )
    elif return_edge > 0:
        verdict, tradeable = "marginal", False
        label = (
            f"ดีกว่าค่าฐานเพียง {return_edge:.2f} จุดจาก {signals} สัญญาณ "
            "ยังไม่พอให้ถือเป็นสัญญาณซื้อเดี่ยว ๆ"
        )
    else:
        verdict, tradeable = "no_edge", False
        label = (
            f"แย่กว่าการถือหุ้นเฉย ๆ {abs(return_edge):.2f} จุดจาก {signals} สัญญาณ "
            "ในอดีตยังไม่มีหลักฐานว่าใช้ทำกำไรได้"
        )

    return {
        "available": True,
        "verdict": verdict,
        "tradeable": tradeable,
        "label": label,
        "signals": signals,
        "horizon_bars": horizon,
        "average_return_pct_net": stats.get("average_return_pct_net"),
        "hit_rate_pct": stats.get("hit_rate_pct"),
        "average_max_drawdown_pct": stats.get("average_max_drawdown_pct"),
        "baseline_return_pct_net": baseline.get("average_return_pct_net"),
        "baseline_hit_rate_pct": baseline.get("hit_rate_pct"),
        "return_edge_pp": round(return_edge, 3),
        "hit_rate_edge_pp": round(hit_edge, 2),
    }


def best_evidence(patterns: list[str], timeframe: str) -> dict[str, Any]:
    """Evidence for the strongest supported pattern among those that fired."""
    rows = [{**pattern_edge(name, timeframe), "pattern": name} for name in patterns]
    tradeable = [row for row in rows if row.get("tradeable")]
    if tradeable:
        return max(tradeable, key=lambda row: row.get("return_edge_pp") or 0)
    measured = [row for row in rows if row.get("available")]
    if measured:
        return max(measured, key=lambda row: row.get("return_edge_pp") or -999)
    return rows[0] if rows else {"available": False, "tradeable": False, "label": "-", "verdict": "unmeasured"}
