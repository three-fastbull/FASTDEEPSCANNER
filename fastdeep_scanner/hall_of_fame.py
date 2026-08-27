from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from .data_io import load_price_csv, load_universe_metadata
from .models import StockCandle


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PRICE_PATH = ROOT / "data" / "fastdeep_hall_prices.csv"
DEFAULT_SOURCE_PATH = ROOT / "data" / "fastdeep_hall_prices_source.json"
MIN_MONTHS_FOR_TEN_YEARS = 120


@dataclass
class _MonthlyRecord:
    contribution_date: date
    latest_date: date
    purchase_price: float
    close: float


def _adjusted(candle: StockCandle) -> float:
    value = candle.adjusted_close if candle.adjusted_close is not None else candle.close
    return float(value or 0)


def _purchase_price(candle: StockCandle) -> float:
    value = candle.adjusted_open if candle.adjusted_open is not None else _adjusted(candle)
    return float(value or 0)


def _monthly_records(candles: list[StockCandle], evaluation_date: date) -> list[_MonthlyRecord]:
    """Collapse Yahoo's occasional current-month duplicate without adding a second DCA."""
    records: dict[tuple[int, int], _MonthlyRecord] = {}
    for candle in sorted(candles, key=lambda item: item.date):
        if candle.date > evaluation_date:
            continue
        if candle.adjusted_close is None or candle.adjusted_open is None:
            continue
        close = _adjusted(candle)
        purchase_price = _purchase_price(candle)
        if close <= 0 or purchase_price <= 0:
            continue
        key = (candle.date.year, candle.date.month)
        existing = records.get(key)
        if existing is None:
            records[key] = _MonthlyRecord(
                contribution_date=date(candle.date.year, candle.date.month, 1),
                latest_date=candle.date,
                purchase_price=purchase_price,
                close=close,
            )
            continue
        existing.latest_date = candle.date
        existing.close = close
    return [records[key] for key in sorted(records)]


def _xnpv(rate: float, cashflows: list[tuple[date, float]]) -> float:
    origin = cashflows[0][0]
    return sum(
        amount / ((1 + rate) ** ((when - origin).days / 365.0))
        for when, amount in cashflows
    )


def xirr(cashflows: list[tuple[date, float]]) -> float | None:
    """Annualized money-weighted return for irregular DCA cash flows."""
    if not cashflows or not any(value < 0 for _, value in cashflows) or not any(
        value > 0 for _, value in cashflows
    ):
        return None
    low = -0.9999
    high = 1.0
    low_value = _xnpv(low, cashflows)
    high_value = _xnpv(high, cashflows)
    while high_value > 0 and high < 1_000:
        high *= 2
        high_value = _xnpv(high, cashflows)
    if low_value * high_value > 0:
        return None
    for _ in range(160):
        midpoint = (low + high) / 2
        value = _xnpv(midpoint, cashflows)
        if abs(value) < 0.000001:
            return midpoint
        if value > 0:
            low = midpoint
        else:
            high = midpoint
    return (low + high) / 2


def _maximum_drawdown(values: list[float]) -> float | None:
    peak = 0.0
    worst = 0.0
    for value in values:
        if value <= 0:
            continue
        peak = max(peak, value)
        if peak:
            worst = min(worst, value / peak - 1)
    return abs(worst) * 100 if peak else None


def _ten_year_start(as_of: date) -> date:
    return date(as_of.year - 10, as_of.month, 1)


def _groups(value: str) -> set[str]:
    return {item.strip() for item in value.replace(",", "|").split("|") if item.strip()}


def evaluate_symbol(
    candles: list[StockCandle],
    *,
    initial_investment: float = 100_000,
    monthly_dca: float = 5_000,
    as_of: date | None = None,
) -> dict[str, Any] | None:
    valid_dates = [
        item.date for item in candles if _adjusted(item) > 0 and _purchase_price(item) > 0
    ]
    if not valid_dates:
        return None
    evaluation_date = as_of or max(valid_dates)
    monthly = _monthly_records(candles, evaluation_date)
    if not monthly:
        return None
    start = _ten_year_start(evaluation_date)
    history = [item for item in monthly if start <= item.contribution_date <= evaluation_date]
    if len(history) < MIN_MONTHS_FOR_TEN_YEARS or not history:
        return None
    if (
        (history[0].contribution_date - start).days > 45
        or (evaluation_date - history[-1].latest_date).days > 45
    ):
        return None
    month_numbers = [item.contribution_date.year * 12 + item.contribution_date.month for item in history]
    if any(current - previous != 1 for previous, current in zip(month_numbers, month_numbers[1:])):
        return None

    shares = 0.0
    cashflows: list[tuple[date, float]] = []
    first_price = history[0].purchase_price
    shares += initial_investment / first_price
    cashflows.append((history[0].contribution_date, -initial_investment))
    for record in history[1:]:
        shares += monthly_dca / record.purchase_price
        cashflows.append((record.contribution_date, -monthly_dca))

    final_price = history[-1].close
    ending_value = shares * final_price
    cashflows.append((history[-1].latest_date, ending_value))
    annualized = xirr(cashflows)
    if annualized is None:
        return None
    years = max(
        (history[-1].latest_date - history[0].contribution_date).days / 365.2425,
        0.01,
    )
    price_cagr = (final_price / first_price) ** (1 / years) - 1 if first_price > 0 else None
    invested = initial_investment + monthly_dca * (len(history) - 1)
    return {
        "start_date": history[0].contribution_date.isoformat(),
        "end_date": history[-1].latest_date.isoformat(),
        "months": len(history),
        "dca_payments": len(history) - 1,
        "years": round(years, 2),
        "initial_investment": round(initial_investment, 2),
        "monthly_dca": round(monthly_dca, 2),
        "total_invested": round(invested, 2),
        "ending_value": round(ending_value, 2),
        "profit": round(ending_value - invested, 2),
        "total_gain_pct": round((ending_value - invested) / invested * 100, 2) if invested else None,
        "wealth_multiple": round(ending_value / invested, 2) if invested else None,
        "annualized_return_pct": annualized * 100,
        "price_cagr_pct": round(price_cagr * 100, 2) if price_cagr is not None else None,
        "max_monthly_drawdown_pct": round(
            _maximum_drawdown([item.close for item in history]) or 0.0,
            2,
        ),
    }


def _source_metadata(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


@lru_cache(maxsize=8)
def _build_cached(
    price_path_text: str,
    price_modified_ns: int,
    universe_path_text: str,
    universe_modified_ns: int,
    min_return: float,
    market: str,
    universe: str,
) -> dict[str, Any]:
    del price_modified_ns, universe_modified_ns
    price_path = Path(price_path_text)
    universe_path = Path(universe_path_text)
    prices = load_price_csv(price_path)
    metadata = load_universe_metadata(universe_path)
    universe_count = sum(
        1
        for item in metadata.values()
        if (market == "ALL" or item["market"] == market)
        and (universe == "ALL" or universe in _groups(item.get("index_groups", "")))
    )
    latest = max((items[-1].date for items in prices.values() if items), default=None)
    leaders: list[dict[str, Any]] = []
    evaluated = 0
    for symbol, candles in prices.items():
        item = metadata.get(symbol)
        if not item:
            continue
        if market != "ALL" and item["market"] != market:
            continue
        if universe != "ALL" and universe not in _groups(item.get("index_groups", "")):
            continue
        result = evaluate_symbol(candles, as_of=latest)
        if result is None:
            continue
        evaluated += 1
        if result["annualized_return_pct"] < min_return:
            continue
        leaders.append(
            {
                "symbol": symbol,
                "name": item.get("name") or symbol,
                "market": item.get("market") or "-",
                "sector": item.get("sector") or "-",
                "index_groups": item.get("index_groups") or "",
                **result,
            }
        )
    leaders.sort(key=lambda row: (-row["annualized_return_pct"], -row["ending_value"], row["symbol"]))
    for rank, row in enumerate(leaders, start=1):
        row["rank"] = rank
    return {
        "available": evaluated > 0,
        "as_of": latest.isoformat() if latest else "",
        "minimum_return_pct": min_return,
        "evaluated": evaluated,
        "universe_count": universe_count,
        "insufficient_history": universe_count - evaluated,
        "qualified": len(leaders),
        "leaders": leaders,
    }


def build_hall_of_fame(
    *,
    price_path: str | Path = DEFAULT_PRICE_PATH,
    universe_path: str | Path | None = None,
    min_return: float = 15.0,
    market: str = "ALL",
    universe: str = "ALL",
) -> dict[str, Any]:
    price_path = Path(price_path).resolve()
    universe_path = Path(universe_path or (ROOT / "data" / "fastdeep_universe.csv")).resolve()
    if not price_path.exists():
        return {
            "available": False,
            "message": "ยังไม่มีข้อมูลราคารายเดือนย้อนหลัง 10 ปีสำหรับ Hall of Fame",
            "leaders": [],
        }
    result = _build_cached(
        str(price_path),
        price_path.stat().st_mtime_ns,
        str(universe_path),
        universe_path.stat().st_mtime_ns,
        round(float(min_return), 2),
        market.upper(),
        universe.upper(),
    )
    source_path = price_path.with_name(f"{price_path.stem}_source.json")
    return {
        **result,
        "source": _source_metadata(source_path),
        "methodology": {
            "period": "กรอบย้อนหลัง 10 ปี ต้องมีข้อมูลอย่างน้อย 120 เดือนต่อเนื่อง โดยไม่ข้ามเดือนที่หาย",
            "initial_investment_thb": 100_000,
            "monthly_dca_thb": 5_000,
            "purchase_timing": "ลงทุนก้อนแรกในเดือนเริ่มต้น แล้ว DCA เริ่มเดือนถัดไป วันที่ 1 หรือราคาเปิดของวันซื้อขายแรกหลังวันที่ 1",
            "ranking_metric": "XIRR คำนึงถึงวันและจำนวนเงิน DCA โดยใช้ปีละ 365 วัน ส่วน CAGR วัดการโตของราคาปรับแล้วจากต้นถึงปลายช่วง",
            "price_basis": "Yahoo Finance Adjusted Close; ใช้ตัวปรับเดียวกันกับราคาเปิดรายเดือน",
            "drawdown": "การลดลงสูงสุดจากจุดสูงสุดของราคาปิดรายเดือน ไม่ใช่ขาดทุนระหว่างวันหรือขาดทุนของพอร์ต DCA",
            "excluded": "แบบจำลองซื้อเศษหุ้นได้ ใช้วันที่ 1 แทนวันลงทุนรายเดือน สมมติค่าเงินคงที่ ไม่รวมค่าธรรมเนียมและภาษี ใช้สมาชิก Universe ปัจจุบันจึงมี survivorship bias ผลย้อนหลังไม่รับประกันอนาคต",
        },
    }
