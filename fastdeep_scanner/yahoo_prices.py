from __future__ import annotations

import csv
import json
import os
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_UNIVERSE = ROOT / "data" / "fastdeep_universe.csv"
DEFAULT_OUTPUT = ROOT / "data" / "fastdeep_prices.csv"
DEFAULT_METADATA = ROOT / "data" / "fastdeep_prices_source.json"
DEFAULT_STATUS = ROOT / "data" / "fastdeep_price_update_status.json"


@dataclass(frozen=True)
class DownloadSummary:
    symbols: int
    succeeded: int
    rows: int
    output: Path
    failed: list[str]
    latest_candle_date: str


class PriceUpdateInProgress(RuntimeError):
    """Raised when another price update owns the update lock."""


def load_universe(path: str | Path = DEFAULT_UNIVERSE) -> list[str]:
    path = Path(path)
    if not path.exists():
        return []
    symbols: list[str] = []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or row.get("ticker") or "").strip()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
    return symbols


def _chart_url(symbol: str, range_value: str, interval: str) -> str:
    encoded = urllib.parse.quote(symbol, safe="")
    query = urllib.parse.urlencode(
        {
            "range": range_value,
            "interval": interval,
            "events": "history",
            "includeAdjustedClose": "true",
        }
    )
    return f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?{query}"


def _download_json(url: str, timeout: int = 20) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 FastDeepScanner/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _atomic_write(path: Path, body: str) -> None:
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temp.write_text(body, encoding="utf-8")
    temp.replace(path)


def _write_status(path: Path, state: str, **details: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(
        path,
        json.dumps(
            {"state": state, "updated_at": datetime.now(UTC).isoformat(), **details},
            ensure_ascii=False,
            indent=2,
        ),
    )


def _acquire_lock(path: Path, stale_lock_minutes: int) -> None:
    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        age_seconds = time.time() - path.stat().st_mtime
        if age_seconds <= stale_lock_minutes * 60:
            raise PriceUpdateInProgress("Price update is already running") from exc
        for child in path.iterdir():
            child.unlink(missing_ok=True)
        path.rmdir()
        path.mkdir(parents=True, exist_ok=False)
    (path / "owner.json").write_text(
        json.dumps({"pid": os.getpid(), "started_at": datetime.now(UTC).isoformat()}),
        encoding="utf-8",
    )


def fetch_symbol_prices(
    symbol: str,
    range_value: str = "2y",
    interval: str = "1d",
    timeout: int = 12,
) -> list[dict[str, str | float]]:
    payload = _download_json(_chart_url(symbol, range_value, interval), timeout=timeout)
    result = payload.get("chart", {}).get("result", [])
    if not result:
        error = payload.get("chart", {}).get("error") or {}
        description = error.get("description") or "no chart result"
        raise RuntimeError(f"{symbol}: {description}")

    chart = result[0]
    timestamps = chart.get("timestamp") or []
    quote = (chart.get("indicators", {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    rows: list[dict[str, str | float]] = []
    for idx, timestamp in enumerate(timestamps):
        values = [
            opens[idx] if idx < len(opens) else None,
            highs[idx] if idx < len(highs) else None,
            lows[idx] if idx < len(lows) else None,
            closes[idx] if idx < len(closes) else None,
        ]
        if any(value is None for value in values):
            continue
        rows.append(
            {
                "date": datetime.fromtimestamp(int(timestamp)).date().isoformat(),
                "symbol": symbol,
                "open": round(float(values[0]), 6),
                "high": round(float(values[1]), 6),
                "low": round(float(values[2]), 6),
                "close": round(float(values[3]), 6),
                "volume": int(volumes[idx] or 0) if idx < len(volumes) else 0,
            }
        )
    return rows


def update_prices_from_yahoo(
    universe_path: str | Path = DEFAULT_UNIVERSE,
    output_path: str | Path = DEFAULT_OUTPUT,
    range_value: str = "2y",
    interval: str = "1d",
    pause_seconds: float = 0.25,
    min_success_ratio: float = 0.97,
    stale_lock_minutes: int = 180,
    max_workers: int = 6,
    request_timeout: int = 12,
) -> DownloadSummary:
    symbols = load_universe(universe_path)
    if not symbols:
        raise RuntimeError(f"No symbols found in {Path(universe_path)}")

    output = Path(output_path)
    status_path = output.with_name(DEFAULT_STATUS.name)
    lock_path = output.with_name("fastdeep_price_update.lock")
    _acquire_lock(lock_path, stale_lock_minutes)
    _write_status(status_path, "running", symbols_requested=len(symbols), output=str(output))

    rows: list[dict[str, str | float]] = []
    failed: list[str] = []
    try:
        def download(symbol: str) -> tuple[str, list[dict[str, str | float]], str | None]:
            try:
                return symbol, fetch_symbol_prices(symbol, range_value, interval, timeout=request_timeout), None
            except Exception as exc:  # noqa: BLE001
                return symbol, [], str(exc)

        processed = 0
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
            futures = [executor.submit(download, symbol) for symbol in symbols]
            for future in as_completed(futures):
                symbol, symbol_rows, error = future.result()
                processed += 1
                if error:
                    failed.append(f"{symbol}: {error}")
                else:
                    rows.extend(symbol_rows)
                if processed % 25 == 0 or processed == len(symbols):
                    _write_status(
                        status_path,
                        "running",
                        symbols_requested=len(symbols),
                        symbols_processed=processed,
                        symbols_succeeded=processed - len(failed),
                        failed_count=len(failed),
                        output=str(output),
                    )
                if pause_seconds:
                    time.sleep(pause_seconds)

        retry_symbols = [item.split(":", 1)[0] for item in failed]
        if retry_symbols:
            failed = []
            _write_status(
                status_path,
                "running",
                symbols_requested=len(symbols),
                symbols_processed=processed,
                symbols_succeeded=processed - len(retry_symbols),
                failed_count=len(retry_symbols),
                retrying=len(retry_symbols),
                output=str(output),
            )
            retry_completed = 0
            for symbol in retry_symbols:
                try:
                    rows.extend(fetch_symbol_prices(symbol, range_value, interval, timeout=max(20, request_timeout)))
                except Exception as exc:  # noqa: BLE001
                    failed.append(f"{symbol}: {exc}")
                retry_completed += 1
                if retry_completed % 5 == 0 or retry_completed == len(retry_symbols):
                    _write_status(
                        status_path,
                        "running",
                        symbols_requested=len(symbols),
                        symbols_processed=processed,
                        symbols_succeeded=processed - len(retry_symbols) + retry_completed - len(failed),
                        failed_count=len(failed),
                        retrying=len(retry_symbols),
                        retry_processed=retry_completed,
                        output=str(output),
                    )
                time.sleep(max(0.2, pause_seconds))

        succeeded = len(symbols) - len(failed)
        if not rows:
            raise RuntimeError("No price rows downloaded. Check network access or symbols.")
        if succeeded / len(symbols) < min_success_ratio:
            raise RuntimeError(
                f"Only {succeeded}/{len(symbols)} symbols downloaded; existing price data was kept unchanged."
            )

        output.parent.mkdir(parents=True, exist_ok=True)
        rows.sort(key=lambda row: (str(row["symbol"]), str(row["date"])))
        latest_candle_date = max(str(row["date"]) for row in rows)
        temp_output = output.with_name(f".{output.name}.{uuid4().hex}.tmp")
        with temp_output.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["date", "symbol", "open", "high", "low", "close", "volume"],
            )
            writer.writeheader()
            writer.writerows(rows)
        temp_output.replace(output)

        metadata_path = output.with_name(f"{output.stem}_source.json")
        metadata = {
            "source": "Yahoo Finance",
            "range": range_value,
            "interval": interval,
            "updated_at": datetime.now(UTC).isoformat(),
            "latest_candle_date": latest_candle_date,
            "symbols_requested": len(symbols),
            "symbols_succeeded": succeeded,
            "rows_downloaded": len(rows),
            "failed": failed,
        }
        _atomic_write(metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2))
        _write_status(
            status_path,
            "complete",
            symbols_requested=len(symbols),
            symbols_succeeded=succeeded,
            failed_count=len(failed),
            latest_candle_date=latest_candle_date,
            rows_downloaded=len(rows),
        )
        return DownloadSummary(
            symbols=len(symbols),
            succeeded=succeeded,
            rows=len(rows),
            output=output,
            failed=failed,
            latest_candle_date=latest_candle_date,
        )
    except Exception as exc:
        _write_status(status_path, "failed", symbols_requested=len(symbols), error=str(exc))
        raise
    finally:
        for child in lock_path.glob("*") if lock_path.exists() else []:
            child.unlink(missing_ok=True)
        if lock_path.exists():
            lock_path.rmdir()


FX_PAIR_SYMBOLS = {
    "THB": "USDTHB=X",
    "HKD": "USDHKD=X",
    "CNY": "USDCNY=X",
    "JPY": "USDJPY=X",
    "EUR": "USDEUR=X",
    "GBP": "USDGBP=X",
    "SGD": "USDSGD=X",
    "TWD": "USDTWD=X",
    "KRW": "USDKRW=X",
    "INR": "USDINR=X",
    "AUD": "USDAUD=X",
    "CAD": "USDCAD=X",
    "CHF": "USDCHF=X",
    "SEK": "USDSEK=X",
    "NOK": "USDNOK=X",
    "DKK": "USDDKK=X",
    "BRL": "USDBRL=X",
    "MXN": "USDMXN=X",
    "ZAR": "USDZAR=X",
}


def update_fx_rates(
    out_path: str | Path | None = None,
    *,
    timeout: int = 12,
    pause_seconds: float = 0.15,
) -> dict:
    """Store units-per-USD for every reporting currency the universe can use.

    Valuation refuses to mix a HKD price with a CNY statement, so these dated
    rates are what allows a cross-currency P/E to be published at all.
    """
    out_path = Path(out_path) if out_path else ROOT / "data" / "fastdeep_fx_rates.json"
    previous: dict = {}
    if out_path.exists():
        try:
            previous = json.loads(out_path.read_text(encoding="utf-8")).get("rates", {})
        except (OSError, json.JSONDecodeError):
            previous = {}

    rates: dict[str, float] = {}
    failed: list[str] = []
    for code, pair in FX_PAIR_SYMBOLS.items():
        try:
            payload = _download_json(_chart_url(pair, "5d", "1d"), timeout=timeout)
            result = (payload.get("chart", {}).get("result") or [{}])[0]
            closes = [
                value
                for value in ((result.get("indicators", {}).get("quote") or [{}])[0].get("close") or [])
                if value is not None
            ]
            price = float(closes[-1]) if closes else float(result.get("meta", {}).get("regularMarketPrice") or 0)
            if price > 0:
                rates[code] = round(price, 6)
            else:
                failed.append(code)
        except Exception:  # noqa: BLE001 - a single missing pair must not stop the run
            failed.append(code)
        if pause_seconds:
            time.sleep(pause_seconds)

    for code, value in previous.items():
        rates.setdefault(code, value)

    payload = {
        "base": "USD",
        "quote": "units of currency per 1 USD",
        "source": "Yahoo Finance FX chart",
        "updated_at": datetime.now(UTC).isoformat(),
        "failed": failed,
        "rates": rates,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(out_path, json.dumps(payload, ensure_ascii=False, indent=2))
    return payload
