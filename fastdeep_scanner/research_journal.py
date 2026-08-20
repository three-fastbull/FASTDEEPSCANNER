from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "storage" / "fastdeep_research_journal.json"
STATUSES = {"Watch", "Research", "Approved", "Owned", "Exit"}
MOAT_VALUES = {"wide", "strong", "medium", "niche", "weak"}
TREND_VALUES = {"leader", "beneficiary", "automation", "neutral", "laggard"}
_LOCK = threading.Lock()


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"items": {}}


def _blank(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "status": "Watch",
        "note": "",
        "moat": "",
        "ai_trend": "",
        "fair_value": 0.0,
        "thesis": "",
        "updated_at": None,
        "research_verified": False,
    }


def _is_verified(item: dict[str, Any]) -> bool:
    """Business quality counts as reviewed only once a human recorded a judgement."""
    return bool(item.get("moat")) and bool(item.get("ai_trend"))


def load_journal(path: str | Path = DEFAULT_PATH) -> dict[str, dict[str, Any]]:
    items = _read(Path(path)).get("items", {})
    return {
        symbol: {**item, "research_verified": _is_verified(item)}
        for symbol, item in items.items()
        if isinstance(item, dict)
    }


def get_research(symbol: str, path: str | Path = DEFAULT_PATH) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    item = _read(Path(path)).get("items", {}).get(symbol)
    if not isinstance(item, dict):
        return _blank(symbol)
    return {**_blank(symbol), **item, "research_verified": _is_verified(item)}


def save_research(
    symbol: str,
    status: str,
    note: str = "",
    path: str | Path = DEFAULT_PATH,
    *,
    moat: str = "",
    ai_trend: str = "",
    fair_value: float | str | None = None,
    thesis: str = "",
) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("กรุณาระบุชื่อย่อหุ้น")
    if status not in STATUSES:
        raise ValueError("สถานะ Research ไม่ถูกต้อง")
    moat = (moat or "").strip().lower()
    ai_trend = (ai_trend or "").strip().lower()
    if moat and moat not in MOAT_VALUES:
        raise ValueError("ค่า Moat ไม่ถูกต้อง")
    if ai_trend and ai_trend not in TREND_VALUES:
        raise ValueError("ค่าแนวโน้มธุรกิจไม่ถูกต้อง")
    try:
        fair = float(fair_value) if fair_value not in (None, "") else 0.0
    except (TypeError, ValueError) as exc:
        raise ValueError("มูลค่าที่เหมาะสมต้องเป็นตัวเลข") from exc
    if fair < 0:
        raise ValueError("มูลค่าที่เหมาะสมต้องไม่ติดลบ")
    if status in {"Approved", "Owned"} and not (moat and ai_trend):
        raise ValueError("ต้องบันทึก Moat และแนวโน้มธุรกิจก่อนเปลี่ยนสถานะเป็น Approved หรือ Owned")

    path = Path(path)
    with _LOCK:
        payload = _read(path)
        items = payload.setdefault("items", {})
        previous = items.get(symbol) if isinstance(items.get(symbol), dict) else {}
        record = {
            "symbol": symbol,
            "status": status,
            "note": note.strip()[:1000],
            "moat": moat or str(previous.get("moat") or ""),
            "ai_trend": ai_trend or str(previous.get("ai_trend") or ""),
            "fair_value": fair or float(previous.get("fair_value") or 0.0),
            "thesis": (thesis.strip() or str(previous.get("thesis") or ""))[:2000],
            "updated_at": datetime.now(UTC).isoformat(),
        }
        record["research_verified"] = _is_verified(record)
        items[symbol] = record
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
        return record
