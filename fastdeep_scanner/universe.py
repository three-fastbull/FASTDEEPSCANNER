"""Dated, validated index membership and coverage of the registered universe."""

from __future__ import annotations

import csv
import hashlib
import importlib
import io
import json
import re
import sys
import urllib.request
from collections import Counter
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_UNIVERSE = ROOT / "data" / "fastdeep_universe.csv"
DEFAULT_SOURCE = ROOT / "data" / "fastdeep_universe_source.json"
FIELDS = ("symbol", "name", "market", "sector", "index_groups")

GROUPS = {
    "SP500": {"label": "S&P 500", "market": "US", "bounds": (490, 520), "parser": "ssga", "basis": "ETF holdings proxy", "provider": "State Street SPY", "url": "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx"},
    "NASDAQ100": {"label": "Nasdaq-100", "market": "US", "bounds": (95, 110), "parser": "ishares", "basis": "ETF holdings proxy", "provider": "BlackRock IQQ", "url": "https://www.ishares.com/us/products/351653/ishares-nasdaq-100-etf/latest-holdings.csv"},
    "SP400": {"label": "S&P MidCap 400", "market": "US", "bounds": (390, 415), "parser": "ssga", "basis": "ETF holdings proxy", "provider": "State Street MDY", "url": "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-mdy.xlsx"},
    "CSI300": {"label": "CSI 300", "market": "CN", "bounds": (300, 300), "parser": "csi", "basis": "Official index constituents", "provider": "China Securities Index", "url": "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/cons/000300cons.xls"},
    "HSI": {"label": "Hang Seng Index", "market": "HK", "bounds": (85, 110), "parser": "ishares", "basis": "ETF holdings proxy", "provider": "BlackRock 3115", "url": "https://www.blackrock.com/hk/en/products/284479/fund/1478358625333.ajax?fileType=csv&fileName=3115_holdings&dataType=fund"},
    "HSTECH": {"label": "Hang Seng Tech", "market": "HK", "bounds": (30, 35), "parser": "ishares", "basis": "ETF holdings proxy", "provider": "BlackRock 3067", "url": "https://www.blackrock.com/hk/en/products/315923/fund/1478358625333.ajax?fileType=csv&fileName=3067_holdings&dataType=fund"},
    "CHINA50": {"label": "China 50 (original selection)", "market": "CN"},
    "SET50": {"label": "SET50", "market": "TH"},
    "SET100": {"label": "SET100", "market": "TH"},
    "MAI": {"label": "mai (tracked)", "market": "TH"},
    "SET_SAMPLE": {"label": "Thai watchlist", "market": "TH"},
    "WATCHLIST": {"label": "Retained watchlist", "market": "ALL"},
}
MANAGED_GROUPS = tuple(key for key, config in GROUPS.items() if config.get("url"))


def _library(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        local = str(ROOT / "storage" / "python-deps")
        if local not in sys.path:
            sys.path.insert(0, local)
        try:
            return importlib.import_module(name)
        except ImportError as exc:
            raise RuntimeError("Run Install-FastDeepDataTools.ps1 to install index data readers") from exc


def _date(value: Any) -> date:
    text = str(value).strip().removeprefix("As of ")
    if text.endswith(".0"):
        text = text[:-2]
    # HSI publishes September as the four-letter "Sept", which %b never matches.
    # Trimming it keeps the one month that would otherwise silently freeze the
    # index membership for four weeks a year.
    text = re.sub(r"Sept\b", "Sep", text, flags=re.IGNORECASE)
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%b %d, %Y", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unrecognized holdings date: {text}")


def normalize_symbol(value: Any, market: str) -> str:
    raw = str(value).strip().upper()
    if market == "HK":
        if not raw.isdigit() or not 0 < int(raw) < 100000:
            raise ValueError(f"Invalid HK exchange code: {raw}")
        return f"{int(raw):04d}.HK"
    if not re.fullmatch(r"[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z])?", raw):
        raise ValueError(f"Invalid US equity symbol: {raw}")
    return raw.replace(".", "-")


def parse_ishares(body: bytes, market: str) -> tuple[date, list[dict[str, str]]]:
    rows = list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))
    stamp = next(_date(row[1]) for row in rows if len(row) > 1 and row[0] == "Fund Holdings as of")
    header = next(i for i, row in enumerate(rows) if "Ticker" in row and "Asset Class" in row)
    members = []
    for values in rows[header + 1:]:
        row = dict(zip(rows[header], values))
        if row.get("Asset Class") != "Equity":
            continue
        if market == "HK" and row.get("Market Currency") != "HKD":
            raise ValueError("Expected the HKD share counter, not an ADR or RMB counter")
        members.append({"symbol": normalize_symbol(row["Ticker"], market), "name": row["Name"].strip(), "sector": row.get("Sector") or "Unknown", "market": market})
    return stamp, members


def parse_ssga(body: bytes, market: str = "US") -> tuple[date, list[dict[str, str]]]:
    book = _library("openpyxl").load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    try:
        rows = list(book.active.values)
    finally:
        book.close()
    stamp = next(_date(row[1]) for row in rows if row and row[0] == "Holdings:")
    header = next(i for i, row in enumerate(rows) if "Ticker" in row and "Identifier" in row)
    members = []
    for values in rows[header + 1:]:
        row = dict(zip(rows[header], values))
        name, ticker = str(row.get("Name") or "").strip(), str(row.get("Ticker") or "").strip()
        if not ticker or not row.get("Identifier") or not row.get("Shares Held"):
            continue
        if ticker in ("USD", "CASH_USD") or name.upper() in ("US DOLLAR", "U.S. DOLLAR") or name.upper().startswith(("CASH", "CONTRA ")):
            continue
        if not re.fullmatch(r"[A-Z0-9]{9}", str(row["Identifier"])):
            raise ValueError(f"Unrecognized equity identifier for {ticker}")
        if row.get("Local Currency") != "USD":
            raise ValueError(f"Unexpected trading currency for {ticker}")
        sector = row.get("Sector")
        members.append({"symbol": normalize_symbol(ticker, market), "name": name, "market": market, "sector": sector if sector and sector != "-" else "Unknown"})
    return stamp, members


def parse_csi(body: bytes, market: str = "CN") -> tuple[date, list[dict[str, str]]]:
    book = _library("xlrd").open_workbook(file_contents=body)
    sheet = book.sheet_by_index(0)
    headings = sheet.row_values(0)
    column = lambda label: next(i for i, heading in enumerate(headings) if label in str(heading))
    code_col, name_col = column("Constituent Code"), column("Constituent Name(Eng)")
    index_col = column("Index Code")
    exchange_col = column("Exchange(Eng)")
    members, stamps = [], set()
    for number in range(1, sheet.nrows):
        row = sheet.row_values(number)
        if str(row[index_col]).removesuffix(".0").zfill(6) != "000300":
            raise ValueError("Expected CSI 300 (000300), not another index")
        stamps.add(_date(row[0]))
        raw = str(row[code_col]).removesuffix(".0").zfill(6)
        exchange = str(row[exchange_col]).replace(" ", "").lower()
        suffix = {"shanghaistockexchange": ".SS", "shenzhenstockexchange": ".SZ"}.get(exchange)
        if not suffix or not re.fullmatch(r"\d{6}", raw):
            raise ValueError(f"Unknown CSI exchange or code: {raw}, {exchange}")
        members.append({"symbol": raw + suffix, "name": str(row[name_col]).strip(), "market": market, "sector": "Unknown"})
    if len(stamps) != 1:
        raise ValueError("CSI file must contain one consistent as-of date")
    return stamps.pop(), members


def validate_members(group: str, stamp: date, members: list[dict[str, str]], today: date | None = None) -> None:
    today = today or date.today()
    if stamp > today or (today - stamp).days > 14:
        raise ValueError(f"Holdings are future-dated or stale: {stamp}")
    low, high = GROUPS[group]["bounds"]
    if not low <= len(members) <= high:
        raise ValueError(f"{group}: received {len(members)} equities; expected {low}..{high}")
    if len({row["symbol"] for row in members}) != len(members):
        raise ValueError(f"{group}: duplicate symbols in source")
    if any(not row.get("name") or row.get("market") != GROUPS[group]["market"] for row in members):
        raise ValueError(f"{group}: missing company name or incorrect market")


def read_universe(path: str | Path = DEFAULT_UNIVERSE) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len({row["symbol"] for row in rows}) != len(rows):
        raise ValueError("Existing universe contains duplicate symbols")
    return rows


def merge_memberships(existing: list[dict[str, str]], snapshots: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    rows = {row["symbol"]: dict(row) for row in existing}
    tags = {symbol: set(row.get("index_groups", "").split("|")) - set(snapshots) - {""} for symbol, row in rows.items()}
    for group, members in snapshots.items():
        for member in members:
            symbol = member["symbol"]
            if symbol not in rows:
                rows[symbol] = dict(member)
                tags[symbol] = set()
            else:
                rows[symbol]["market"] = member["market"]
                if rows[symbol].get("sector", "Unknown") in ("Unknown", "", "-", "Other"):
                    rows[symbol]["sector"] = member["sector"]
            tags[symbol].add(group)
            tags[symbol].discard("WATCHLIST")
    # A deletion from an index is not permission to erase a user's tracked stock.
    for symbol, row in rows.items():
        row["index_groups"] = "|".join(sorted(tags[symbol] or {"WATCHLIST"}))
    return sorted(rows.values(), key=lambda row: (row["market"], row["symbol"]))


def _json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 FastDeepScanner/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        body = response.read(8_000_001)
    if len(body) > 8_000_000:
        raise ValueError("Index response exceeded the size limit")
    return body


def update_universe(path: str | Path = DEFAULT_UNIVERSE, *, groups: tuple[str, ...] = MANAGED_GROUPS, dry_run: bool = False, source_path: str | Path | None = None, fetcher=None) -> dict[str, Any]:
    from .yahoo_prices import _atomic_write

    path = Path(path)
    source_path = Path(source_path) if source_path else path.with_name(f"{path.stem}_source.json")
    if set(groups) - set(MANAGED_GROUPS) or not groups:
        raise ValueError(f"Choose managed index groups from {','.join(MANAGED_GROUPS)}")
    lock = path.with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise RuntimeError("An index update is already running; inspect the universe lock before retrying") from exc
    try:
        with handle:
            handle.write(datetime.now(UTC).isoformat())
        existing = read_universe(path)
        metadata = _json(source_path)
        sources = metadata.setdefault("groups", {})
        now = datetime.now(UTC).isoformat()
        snapshots, errors, changes = {}, {}, {}
        for group in dict.fromkeys(groups):
            config = GROUPS[group]
            try:
                body = (fetcher or _download)(config["url"])
                parser = {"ssga": parse_ssga, "ishares": parse_ishares, "csi": parse_csi}[config["parser"]]
                stamp, members = parser(body, config["market"])
                validate_members(group, stamp, members)
                old = {row["symbol"] for row in existing if group in row.get("index_groups", "").split("|")}
                new = {row["symbol"] for row in members}
                if old and len(old - new) / len(old) > 0.35:
                    raise ValueError("More than 35% of existing members disappeared; manual review required")
                snapshots[group] = members
                changes[group] = {"count": len(new), "added": sorted(new - old), "removed": sorted(old - new)}
                sources[group] = {"provider": config["provider"], "url": config["url"], "basis": config["basis"], "as_of": stamp.isoformat(), "checked_at": now, "state": "ready", "sha256": hashlib.sha256(body).hexdigest(), **changes[group]}
                print(f"{group}: {len(new)} equities, as of {stamp}, +{len(new - old)} / -{len(old - new)}", flush=True)
            except Exception as exc:
                errors[group] = str(exc)
                sources[group] = {**sources.get(group, {}), "state": "error", "checked_at": now, "error": str(exc)}
                print(f"{group}: keeping previous membership ({exc})", flush=True)
        updated = merge_memberships(existing, snapshots)
        metadata.update({"updated_at": now, "symbols": len(updated), "by_market": dict(Counter(row["market"] for row in updated)), "errors": errors})
        if not dry_run:
            if snapshots:
                backup = path.parent.parent / "storage" / "universe_backups" / f"{datetime.now(UTC):%Y%m%dT%H%M%S%f}_{path.name}"
                backup.parent.mkdir(parents=True, exist_ok=True)
                _atomic_write(backup, path.read_text(encoding="utf-8-sig"))
                output = io.StringIO(newline="")
                writer = csv.DictWriter(output, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows({key: row.get(key, "") for key in FIELDS} for row in updated)
                _atomic_write(path, output.getvalue())
            _atomic_write(source_path, json.dumps(metadata, ensure_ascii=False, indent=2))
        return {"before": len(existing), "after": len(updated), "by_market": metadata["by_market"], "groups": changes, "errors": errors, "dry_run": dry_run}
    finally:
        lock.unlink(missing_ok=True)


@lru_cache(maxsize=4)
def _price_dates(path_text: str, modified_ns: int) -> dict[str, str]:
    latest: dict[str, str] = {}
    with Path(path_text).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            symbol, stamp = row.get("symbol", ""), row.get("date", "")[:10]
            if symbol and stamp > latest.get(symbol, ""):
                latest[symbol] = stamp
    return latest


def price_dates(path: str | Path) -> dict[str, str]:
    path = Path(path)
    return _price_dates(str(path.resolve()), path.stat().st_mtime_ns) if path.exists() else {}


def universe_overview(universe_path: str | Path = DEFAULT_UNIVERSE, *, price_path: str | Path | None = None, coverage_path: str | Path | None = None, today: date | None = None) -> dict[str, Any]:
    from .data_health import expected_eod_date

    universe_path = Path(universe_path)
    rows = read_universe(universe_path)
    directory = universe_path.parent
    latest = price_dates(price_path or directory / "fastdeep_prices.csv")
    coverage = _json(Path(coverage_path) if coverage_path else directory / "fastdeep_financial_coverage.json")
    financials = {item["symbol"]: item for item in coverage.get("items", []) if item.get("symbol")}
    sources = _json(universe_path.with_name(f"{universe_path.stem}_source.json"))
    expected = expected_eod_date(today).isoformat()
    source_groups = sources.get("groups", {})

    def counts(members: list[dict[str, str]]) -> dict[str, int]:
        symbols = {row["symbol"] for row in members}
        quality = [financials.get(symbol, {}) for symbol in symbols]
        available = sum(symbol in latest for symbol in symbols)
        fresh = sum(latest.get(symbol, "") >= expected for symbol in symbols)
        cached = sum(item.get("status", "missing") != "missing" and not item.get("cache_error") for item in quality)
        return {"registered": len(symbols), "price_available": available, "price_fresh": fresh, "price_stale": available - fresh, "price_missing": len(symbols) - available, "financial_cached": cached, "annual_5y": sum(bool(item.get("annual_complete")) for item in quality), "financial_complete": sum(item.get("status") == "complete" for item in quality)}

    groups = []
    keys = list(GROUPS) + sorted({tag for row in rows for tag in row.get("index_groups", "").split("|") if tag and tag not in GROUPS})
    for key in keys:
        members = [row for row in rows if key in row.get("index_groups", "").split("|")]
        if not members:
            continue
        config = GROUPS.get(key, {"label": key, "market": "ALL"})
        source = dict(source_groups.get(key, {}))
        as_of = source.get("as_of")
        if as_of and source.get("state") == "ready" and ((today or date.today()) - date.fromisoformat(as_of)).days > 14:
            source["state"] = "stale"
        groups.append({"id": key, "label": config["label"], "market": config["market"], **counts(members), "source": {"provider": source.get("provider", "Existing local list"), "basis": source.get("basis", "Tracked selection; not refreshed by this update"), "url": source.get("url"), "as_of": as_of, "state": source.get("state", "not_verified"), "error": source.get("error")}})
    return {"symbols": rows, "totals": counts(rows), "groups": groups, "markets": [{"id": market, **counts([row for row in rows if row["market"] == market])} for market in ("US", "CN", "HK", "TH")], "membership_updated_at": sources.get("updated_at"), "financial_audited_at": coverage.get("generated_at"), "expected_eod_date": expected}
