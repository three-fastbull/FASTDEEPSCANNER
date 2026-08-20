from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PRICE_PATH = ROOT / "data" / "fastdeep_prices.csv"
DEFAULT_STATUS_PATH = ROOT / "data" / "fastdeep_price_update_status.json"
DEFAULT_FINANCIAL_CACHE_DIR = ROOT / "data" / "financial_cache"
DEFAULT_FINANCIAL_STATUS_PATH = ROOT / "data" / "fastdeep_financial_update_status.json"


def expected_eod_date(today: date | None = None) -> date:
    candidate = (today or datetime.now().date()) - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


@lru_cache(maxsize=8)
def _csv_stats(path_text: str, modified_ns: int) -> tuple[str | None, int]:
    latest: date | None = None
    symbols: set[str] = set()
    with Path(path_text).open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            symbol = (row.get("symbol") or row.get("ticker") or "").strip()
            value = (row.get("date") or row.get("timestamp") or "").strip()[:10]
            if symbol:
                symbols.add(symbol)
            try:
                current = date.fromisoformat(value)
            except ValueError:
                continue
            if latest is None or current > latest:
                latest = current
    return latest.isoformat() if latest else None, len(symbols)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def price_data_health(
    price_path: str | Path = DEFAULT_PRICE_PATH,
    *,
    status_path: str | Path = DEFAULT_STATUS_PATH,
    today: date | None = None,
) -> dict[str, Any]:
    path = Path(price_path)
    metadata_path = path.with_name(f"{path.stem}_source.json")
    metadata = _read_json(metadata_path)
    status = _read_json(Path(status_path))
    if not path.exists():
        return {
            "state": "missing",
            "can_publish": False,
            "message": "ไม่พบไฟล์ราคา",
            "latest_candle_date": None,
            "expected_eod_date": expected_eod_date(today).isoformat(),
            "symbols_requested": 0,
            "symbols_succeeded": 0,
            "failed_count": 0,
        }

    latest = metadata.get("latest_candle_date")
    symbol_count = int(metadata.get("symbols_succeeded") or 0)
    if not latest or not symbol_count:
        latest, symbol_count = _csv_stats(str(path.resolve()), path.stat().st_mtime_ns)

    expected = expected_eod_date(today)
    try:
        is_fresh = date.fromisoformat(str(latest)) >= expected
    except (TypeError, ValueError):
        is_fresh = False
    requested = int(metadata.get("symbols_requested") or symbol_count)
    failed = metadata.get("failed") or []
    coverage = symbol_count / requested if requested else 0.0
    update_running = status.get("state") == "running"
    degraded = bool(failed) or coverage < 0.97
    if update_running:
        state = "updating"
        message = "กำลังอัปเดตราคา - ใช้ข้อมูลชุดก่อนหน้าระหว่างรอ"
    elif not is_fresh:
        state = "stale"
        message = "ข้อมูลราคาเก่า - หยุดใช้ผลสแกนเพื่อการตัดสินใจ"
    elif degraded:
        state = "degraded"
        message = "ข้อมูลราคาบางส่วนไม่ครบ - ตรวจสอบรายชื่อที่ล้มเหลว"
    else:
        state = "ready"
        message = "ข้อมูลราคาพร้อมใช้"

    return {
        "state": state,
        "can_publish": state == "ready",
        "message": message,
        "source": metadata.get("source") or "CSV",
        "updated_at": metadata.get("updated_at"),
        "latest_candle_date": latest,
        "scanner_as_of_date": expected.isoformat(),
        "expected_eod_date": expected.isoformat(),
        "symbols_requested": requested,
        "symbols_succeeded": symbol_count,
        "failed_count": len(failed),
        "coverage": round(coverage * 100, 1),
        "update_status": status.get("state") or "unknown",
    }


def financial_data_health(
    cache_dir: str | Path = DEFAULT_FINANCIAL_CACHE_DIR,
    *,
    status_path: str | Path = DEFAULT_FINANCIAL_STATUS_PATH,
) -> dict[str, Any]:
    cache_dir = Path(cache_dir)
    status = _read_json(Path(status_path))
    files = list(cache_dir.glob("*.json")) if cache_dir.exists() else []
    fresh_cutoff = datetime.now().timestamp() - 8 * 24 * 3600
    fresh = sum(path.stat().st_mtime >= fresh_cutoff for path in files)
    return {
        "state": status.get("state") or ("ready" if files else "missing"),
        "cached_symbols": len(files),
        "fresh_symbols": fresh,
        "symbols_requested": int(status.get("symbols_requested") or 697),
        "failed_count": int(status.get("failed_count") or 0),
        "updated_at": status.get("updated_at"),
    }
