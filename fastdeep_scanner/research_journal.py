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
_LOCK = threading.Lock()


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"items": {}}


def get_research(symbol: str, path: str | Path = DEFAULT_PATH) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    payload = _read(Path(path))
    return payload.get("items", {}).get(symbol, {"symbol": symbol, "status": "Watch", "note": ""})


def save_research(
    symbol: str,
    status: str,
    note: str = "",
    path: str | Path = DEFAULT_PATH,
) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("กรุณาระบุชื่อย่อหุ้น")
    if status not in STATUSES:
        raise ValueError("สถานะ Research ไม่ถูกต้อง")
    path = Path(path)
    with _LOCK:
        payload = _read(path)
        payload.setdefault("items", {})[symbol] = {
            "symbol": symbol,
            "status": status,
            "note": note.strip()[:1000],
            "updated_at": datetime.now(UTC).isoformat(),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
        return payload["items"][symbol]
