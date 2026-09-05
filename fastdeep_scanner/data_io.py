from __future__ import annotations

import csv
import json
import os
import time
from dataclasses import replace
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from .currency import trading_currency
from .models import FundamentalSnapshot, StockCandle
from .research_journal import load_journal
from .sample_data import fundamentals_by_symbol, generate_price_history


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PRICE_CSV = ROOT / "data" / "fastdeep_prices.csv"
DEFAULT_FUNDAMENTALS_CSV = ROOT / "data" / "fastdeep_fundamentals.csv"
DEFAULT_UNIVERSE_CSV = ROOT / "data" / "fastdeep_universe.csv"
DEFAULT_FINANCIAL_CACHE_DIR = ROOT / "data" / "financial_cache"


def _parse_date(value: str):
    value = value.strip()
    if value.isdigit():
        raw = int(value)
        if raw > 10_000_000_000:
            raw = raw // 1000
        return datetime.fromtimestamp(raw).date()
    normalized = value.replace("Z", "+00:00").replace("/", "-")
    return datetime.fromisoformat(normalized).date()


def _value(row: dict[str, str], *names: str, default: str = "") -> str:
    normalized = {key.strip().lower(): value for key, value in row.items() if key is not None}
    for name in names:
        value = normalized.get(name.lower())
        if value not in {None, ""}:
            return value
    return default


def _symbol_from_filename(path: Path) -> str:
    stem = path.stem
    for prefix in ("fastdeep_prices_", "prices_", "tradingview_"):
        if stem.lower().startswith(prefix):
            stem = stem[len(prefix) :]
            break
    return stem.replace("_BK", ".BK").replace("_", ".").upper()


_PRICE_COLUMNS: dict[str, tuple[str, ...]] = {
    "date": ("date", "timestamp", "time", "datetime"),
    "symbol": ("symbol", "ticker", "symbol_name"),
    "open": ("open",),
    "high": ("high",),
    "low": ("low",),
    "close": ("close",),
    "volume": ("volume",),
    "adjusted_close": ("adjusted_close", "adj_close", "adj close"),
    "adjusted_open": ("adjusted_open",),
}


def _price_column_index(header: list[str]) -> dict[str, int]:
    """Resolve every field to a column position once per file.

    The reader used to rebuild a lower-cased copy of each row for every field it
    read - nine times per row across 1.8 million rows - which is what made a cold
    start take twenty seconds.
    """
    lookup = {name.strip().lower(): position for position, name in enumerate(header)}
    resolved: dict[str, int] = {}
    for field, aliases in _PRICE_COLUMNS.items():
        for alias in aliases:
            if alias in lookup:
                resolved[field] = lookup[alias]
                break
    return resolved


def _read_price_csv(path: Path) -> dict[str, list[StockCandle]]:
    grouped: dict[str, list[StockCandle]] = {}
    fallback_symbol = _symbol_from_filename(path)
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return {}
        index = _price_column_index(header)
        required = {"date", "open", "high", "low", "close"}
        if not required <= index.keys():
            missing = ", ".join(sorted(required - index.keys()))
            raise ValueError(f"Price file {path.name} is missing columns: {missing}")
        date_at = index["date"]
        open_at, high_at, low_at, close_at = (
            index["open"], index["high"], index["low"], index["close"]
        )
        symbol_at = index.get("symbol")
        volume_at = index.get("volume")
        adjusted_close_at = index.get("adjusted_close")
        adjusted_open_at = index.get("adjusted_open")
        # A short row would otherwise raise IndexError partway through the file.
        # Only the required columns gate the row; a truncated optional tail still
        # yields a usable candle, which is what the previous reader did.
        span = max(index[field] for field in required) + 1

        def cell(row: list[str], position: int | None) -> str:
            if position is None or position >= len(row):
                return ""
            return row[position].strip()

        for row in reader:
            if len(row) < span:
                continue
            symbol = cell(row, symbol_at) or fallback_symbol
            if not symbol:
                continue
            volume = cell(row, volume_at)
            adjusted_close = cell(row, adjusted_close_at)
            adjusted_open = cell(row, adjusted_open_at)
            grouped.setdefault(symbol, []).append(
                StockCandle(
                    date=_parse_date(row[date_at]),
                    symbol=symbol,
                    open=float(row[open_at]),
                    high=float(row[high_at]),
                    low=float(row[low_at]),
                    close=float(row[close_at]),
                    volume=float(volume) if volume else 0.0,
                    adjusted_close=float(adjusted_close) if adjusted_close else None,
                    adjusted_open=float(adjusted_open) if adjusted_open else None,
                )
            )
    for candles in grouped.values():
        candles.sort(key=lambda item: item.date)
    return grouped


@lru_cache(maxsize=4)
def _cached_price_csv(path_text: str, modified_ns: int) -> dict[str, list[StockCandle]]:
    return _read_price_csv(Path(path_text))


def load_price_csv(path: str | Path) -> dict[str, list[StockCandle]]:
    source = Path(path).resolve()
    return _cached_price_csv(str(source), source.stat().st_mtime_ns)


def completed_eod_candles(
    candles: list[StockCandle],
    as_of_date: date | None = None,
) -> list[StockCandle]:
    """Exclude the current calendar day so this daily scanner never scores an intraday bar."""
    cutoff = as_of_date or date.today()
    return [candle for candle in candles if candle.date < cutoff]


def load_fundamentals_csv(path: str | Path) -> dict[str, FundamentalSnapshot]:
    snapshots: dict[str, FundamentalSnapshot] = {}
    with Path(path).open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            snapshot = FundamentalSnapshot(
                symbol=row["symbol"].strip(),
                name=row.get("name", "").strip(),
                market=row.get("market", "US").strip(),
                sector=row.get("sector", "").strip(),
                roe=float(row.get("roe") or 0),
                roa=float(row.get("roa") or 0),
                debt_to_equity=float(row.get("debt_to_equity") or 0),
                revenue_growth=float(row.get("revenue_growth") or 0),
                profit_growth=float(row.get("profit_growth") or 0),
                gross_margin=float(row.get("gross_margin") or 0),
                net_margin=float(row.get("net_margin") or 0),
                pe=float(row.get("pe") or 0),
                pbv=float(row.get("pbv") or 0),
                dividend_yield=float(row.get("dividend_yield") or 0),
                analyst_upside_pct=float(row.get("analyst_upside_pct") or 0),
                liquidity_score=float(row.get("liquidity_score") or 0),
                moat=row.get("moat", "medium").strip(),
                ai_trend=row.get("ai_trend", "neutral").strip(),
                notes=row.get("notes", "").strip(),
                index_groups=row.get("index_groups", "").strip(),
            )
            snapshots[snapshot.symbol] = snapshot
    return snapshots


def load_universe_metadata(path: str | Path = DEFAULT_UNIVERSE_CSV) -> dict[str, dict[str, str]]:
    path = Path(path)
    if not path.exists():
        return {}
    metadata: dict[str, dict[str, str]] = {}
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or row.get("ticker") or "").strip()
            if not symbol:
                continue
            metadata[symbol] = {
                "name": (row.get("name") or symbol).strip(),
                "market": (row.get("market") or "US").strip(),
                "sector": (row.get("sector") or "Unknown").strip(),
                "index_groups": (row.get("index_groups") or row.get("group") or "").strip(),
            }
    return metadata


def _placeholder_fundamental(symbol: str, metadata: dict[str, str] | None = None) -> FundamentalSnapshot:
    metadata = metadata or {}
    return FundamentalSnapshot(
        symbol=symbol,
        name=metadata.get("name") or symbol,
        market=metadata.get("market") or "US",
        sector=metadata.get("sector") or "Unknown",
        roe=0.0,
        roa=0.0,
        debt_to_equity=0.0,
        revenue_growth=0.0,
        profit_growth=0.0,
        gross_margin=0.0,
        net_margin=0.0,
        pe=0.0,
        pbv=0.0,
        dividend_yield=0.0,
        analyst_upside_pct=0.0,
        liquidity_score=80.0,
        moat="not evaluated",
        ai_trend="not evaluated",
        notes="unverified_fundamentals",
        index_groups=metadata.get("index_groups") or "",
        fundamentals_verified=False,
        research_verified=False,
        source="Not loaded",
    )


def _safe_number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _growth(current: float, previous: float) -> float:
    if not previous:
        return 0.0
    return (current / previous - 1) * 100


def _financial_cache_path(symbol: str) -> Path:
    safe = symbol.replace("/", "_").replace("\\", "_").replace(".", "_")
    return DEFAULT_FINANCIAL_CACHE_DIR / f"{safe}.json"


def _shares_outstanding(metrics: dict[str, Any]) -> float | None:
    """Derive share count from reported net income and basic EPS.

    The statements feed carries no share count, but EPS is reported against the
    same period's net income, so the ratio recovers it well enough to turn
    equity into book value per share.
    """
    eps = _safe_number(metrics.get("basic_eps"))
    net_income = _safe_number(metrics.get("net_income"))
    if not eps or not net_income:
        return None
    shares = net_income / eps
    return shares if shares > 0 else None


def _financial_history_status(payload: dict[str, Any]) -> str:
    quality = payload.get("data_quality") or {}
    if quality.get("status"):
        return str(quality["status"])
    annual_years = {
        str(period.get("period_end") or "")[:4]
        for period in (payload.get("annual") or [])[-5:]
        if period.get("period_end")
    }
    full_quarter_years = {
        str(year)
        for year, periods in (payload.get("quarterly_by_year") or {}).items()
        if {str(item.get("quarter") or "") for item in periods or []}
        >= {"Q1", "Q2", "Q3", "Q4"}
    }
    if len(annual_years) >= 5 and len(annual_years & full_quarter_years) >= 5:
        return "complete"
    return "partial" if annual_years else "missing"


def _snapshot_from_financial_cache(snapshot: FundamentalSnapshot) -> FundamentalSnapshot:
    path = _financial_cache_path(snapshot.symbol)
    try:
        stat = path.stat()
    except OSError:
        return snapshot
    if time.time() - stat.st_mtime > 8 * 24 * 3600:
        return snapshot
    fields = _financial_snapshot_fields(snapshot.symbol, stat.st_mtime_ns)
    if fields is None:
        return snapshot
    return replace(snapshot, **fields)


# load_market_data touches every symbol on every request, so reading and parsing
# all 1,458 statement files each time dominated the response. Keying on the
# file's revision keeps a rewritten statement from serving stale numbers.
@lru_cache(maxsize=4096)
def _financial_snapshot_fields(symbol: str, modified_ns: int) -> dict[str, Any] | None:
    path = _financial_cache_path(symbol)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        annual = payload.get("annual") or []
        latest = annual[-1]
        previous = annual[-2] if len(annual) > 1 else {"metrics": {}}
        metrics = latest.get("metrics") or {}
        previous_metrics = previous.get("metrics") or {}
        ratios = latest.get("ratios") or {}
        history_status = _financial_history_status(payload)
        revenue = _safe_number(metrics.get("total_revenue"))
        net_income = _safe_number(metrics.get("net_income"))
        eps = _safe_number(metrics.get("basic_eps"))
        equity = _safe_number(metrics.get("stockholders_equity"))
        shares = _shares_outstanding(metrics)
        book_value_per_share = equity / shares if shares and equity else 0.0
        return dict(
            roe=_safe_number(ratios.get("roe")),
            roa=_safe_number(ratios.get("roa")),
            debt_to_equity=_safe_number(ratios.get("debt_to_equity")),
            revenue_growth=_growth(revenue, _safe_number(previous_metrics.get("total_revenue"))),
            profit_growth=_growth(net_income, _safe_number(previous_metrics.get("net_income"))),
            gross_margin=_safe_number(ratios.get("gross_margin")),
            net_margin=_safe_number(ratios.get("net_margin")),
            pe=0.0,
            pbv=0.0,
            dividend_yield=0.0,
            analyst_upside_pct=0.0,
            eps=eps,
            book_value_per_share=book_value_per_share,
            reporting_currency=str(payload.get("currency") or "").upper(),
            notes="financials_verified",
            fundamentals_verified=True,
            financial_history_complete=history_status == "complete",
            financial_history_status=history_status,
            source=str(payload.get("source") or "Financial statements cache"),
            as_of=str(latest.get("period_end") or ""),
        )
    except (OSError, json.JSONDecodeError, IndexError, TypeError):
        return None


def load_market_data(
    market_data_path: str | Path | None = None,
    fundamentals_path: str | Path | None = None,
) -> tuple[dict[str, list[StockCandle]], dict[str, FundamentalSnapshot]]:
    force_sample = os.environ.get("FASTDEEP_USE_SAMPLE_DATA") == "1"
    if market_data_path is None and DEFAULT_PRICE_CSV.exists() and not force_sample:
        market_data_path = DEFAULT_PRICE_CSV
    if fundamentals_path is None and DEFAULT_FUNDAMENTALS_CSV.exists() and not force_sample:
        fundamentals_path = DEFAULT_FUNDAMENTALS_CSV

    candles = load_price_csv(market_data_path) if market_data_path else generate_price_history()
    fundamentals = (
        load_fundamentals_csv(fundamentals_path) if fundamentals_path else fundamentals_by_symbol()
    )
    if not force_sample and fundamentals_path is None:
        fundamentals = {
            symbol: replace(
                snapshot,
                notes="unverified_fundamentals",
                fundamentals_verified=False,
                research_verified=False,
                source="Sample values disabled for investment scoring",
            )
            for symbol, snapshot in fundamentals.items()
        }
    universe = load_universe_metadata()
    # Sample runs stay hermetic: the real financial cache and the analyst journal
    # would otherwise leak live data into the demo and into the test suite.
    journal = {} if force_sample else load_journal()
    for symbol in candles:
        if symbol not in fundamentals:
            fundamentals[symbol] = _placeholder_fundamental(symbol, universe.get(symbol))
        elif symbol in universe and not force_sample:
            snapshot = fundamentals[symbol]
            fundamentals[symbol] = replace(
                snapshot,
                index_groups=universe[symbol].get("index_groups", ""),
                market=universe[symbol].get("market") or snapshot.market,
            )
        snapshot = fundamentals[symbol] if force_sample else _snapshot_from_financial_cache(fundamentals[symbol])
        fundamentals[symbol] = _apply_analyst_review(
            replace(snapshot, trading_currency=trading_currency(symbol, snapshot.market)),
            journal.get(symbol),
        )
    return candles, fundamentals


def _apply_analyst_review(
    snapshot: FundamentalSnapshot,
    review: dict[str, Any] | None,
) -> FundamentalSnapshot:
    """Business quality comes from a recorded human judgement, never a default."""
    if not review:
        return snapshot
    verified = bool(review.get("research_verified"))
    return replace(
        snapshot,
        moat=str(review.get("moat") or snapshot.moat),
        ai_trend=str(review.get("ai_trend") or snapshot.ai_trend),
        analyst_fair_value=_safe_number(review.get("fair_value")),
        thesis=str(review.get("thesis") or ""),
        research_status=str(review.get("status") or "Watch"),
        research_verified=verified,
    )


def data_source_label(
    market_data_path: str | Path | None = None,
    fundamentals_path: str | Path | None = None,
) -> str:
    price_path = Path(market_data_path) if market_data_path else DEFAULT_PRICE_CSV
    fundamentals_path = Path(fundamentals_path) if fundamentals_path else DEFAULT_FUNDAMENTALS_CSV
    if price_path.exists():
        source_path = price_path.with_name(f"{price_path.stem}_source.json")
        if source_path.exists():
            try:
                source = json.loads(source_path.read_text(encoding="utf-8"))
                label = (
                    f"{source.get('source', 'CSV')} price data: {price_path.name} "
                    f"({source.get('range', '?')}, {source.get('interval', '?')})"
                )
            except (OSError, json.JSONDecodeError):
                label = f"Real CSV price data: {price_path.name}"
        else:
            label = f"Real CSV price data: {price_path.name}"
        if fundamentals_path.exists():
            return f"{label} + {fundamentals_path.name}"
        return f"{label} + verified financials on demand"
    return "Sample/Demo data - ยังไม่ใช่ราคาจริง"
