"""Paper-trade log: what the scanner suggested versus what actually happened.

Every entry stores the plan as it stood at decision time (entry, stop, targets,
grade, pattern) so the review later compares the real outcome against the plan
rather than against a memory of it.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "storage" / "fastdeep_trade_journal.json"
_LOCK = threading.Lock()
DEFAULT_COST_BPS = 30.0


def _read(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    payload.setdefault("trades", [])
    return payload


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def open_trade(
    symbol: str,
    *,
    entry: float,
    stop: float,
    targets: list[float] | None = None,
    side: str = "BUY",
    timeframe: str = "D",
    pattern: str = "",
    grade: str = "",
    currency: str = "",
    note: str = "",
    opened_on: str = "",
    path: str | Path = DEFAULT_PATH,
) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("กรุณาระบุชื่อย่อหุ้น")
    entry = _number(entry)
    stop = _number(stop)
    if entry <= 0:
        raise ValueError("ราคาเข้าต้องมากกว่า 0")
    side = side.upper() if side.upper() in {"BUY", "SELL"} else "BUY"
    if side == "BUY" and stop >= entry:
        raise ValueError("จุดตัดขาดทุนของฝั่งซื้อต้องต่ำกว่าราคาเข้า")
    if side == "SELL" and 0 < stop <= entry:
        raise ValueError("จุดตัดขาดทุนของฝั่งขายต้องสูงกว่าราคาเข้า")

    trade = {
        "id": uuid4().hex[:12],
        "symbol": symbol,
        "side": side,
        "state": "open",
        "timeframe": timeframe,
        "pattern": pattern,
        "grade": grade,
        "currency": currency,
        "entry": round(entry, 4),
        "stop": round(stop, 4),
        "targets": [round(_number(value), 4) for value in (targets or [])],
        "risk_pct": round(abs(entry - stop) / entry * 100, 2) if entry else 0.0,
        "note": note.strip()[:1000],
        "opened_on": opened_on or date.today().isoformat(),
        "opened_at": datetime.now(UTC).isoformat(),
        "closed_on": None,
        "exit": None,
        "return_pct": None,
        "return_pct_net": None,
        "r_multiple": None,
    }
    with _LOCK:
        path = Path(path)
        payload = _read(path)
        payload["trades"].append(trade)
        _write(path, payload)
    return trade


def close_trade(
    trade_id: str,
    *,
    exit_price: float,
    closed_on: str = "",
    note: str = "",
    cost_bps: float = DEFAULT_COST_BPS,
    path: str | Path = DEFAULT_PATH,
) -> dict[str, Any]:
    exit_price = _number(exit_price)
    if exit_price <= 0:
        raise ValueError("ราคาปิดต้องมากกว่า 0")
    with _LOCK:
        path = Path(path)
        payload = _read(path)
        for trade in payload["trades"]:
            if trade["id"] != trade_id:
                continue
            if trade["state"] == "closed":
                raise ValueError("รายการนี้ปิดไปแล้ว")
            direction = -1 if trade["side"] == "SELL" else 1
            gross = (exit_price / trade["entry"] - 1) * 100 * direction
            risk_pct = trade.get("risk_pct") or 0.0
            trade["state"] = "closed"
            trade["exit"] = round(exit_price, 4)
            trade["closed_on"] = closed_on or date.today().isoformat()
            trade["closed_at"] = datetime.now(UTC).isoformat()
            trade["return_pct"] = round(gross, 3)
            trade["return_pct_net"] = round(gross - cost_bps / 100, 3)
            trade["r_multiple"] = round(gross / risk_pct, 2) if risk_pct else None
            if note:
                trade["note"] = f"{trade['note']} | {note.strip()}"[:1000]
            _write(path, payload)
            return trade
    raise ValueError("ไม่พบรายการเทรดนี้")


def list_trades(path: str | Path = DEFAULT_PATH) -> list[dict[str, Any]]:
    trades = _read(Path(path))["trades"]
    return sorted(trades, key=lambda item: item.get("opened_at") or "", reverse=True)


def journal_summary(path: str | Path = DEFAULT_PATH) -> dict[str, Any]:
    trades = _read(Path(path))["trades"]
    closed = [trade for trade in trades if trade.get("state") == "closed"]
    returns = [trade["return_pct_net"] for trade in closed if trade.get("return_pct_net") is not None]
    r_values = [trade["r_multiple"] for trade in closed if trade.get("r_multiple") is not None]
    return {
        "open_count": sum(trade.get("state") == "open" for trade in trades),
        "closed_count": len(closed),
        "hit_rate_pct": round(sum(value > 0 for value in returns) / len(returns) * 100, 2) if returns else None,
        "average_return_pct_net": round(sum(returns) / len(returns), 3) if returns else None,
        "average_r": round(sum(r_values) / len(r_values), 2) if r_values else None,
        "cost_bps": DEFAULT_COST_BPS,
        "note": "ผลตอบแทนสุทธิหักค่าคอมมิชชันและ slippage ประมาณการไปแล้ว",
    }
