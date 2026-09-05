from __future__ import annotations

import csv
import json
import os
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
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


class PriceUpdateTimeout(RuntimeError):
    """Raised when the whole download exceeds its deadline.

    Distinct from a per-request timeout: the provider is answering, just far too
    slowly to finish the universe, and the caller should retry later rather than
    treat it as a data error.
    """


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


def load_universe_markets(path: str | Path = DEFAULT_UNIVERSE) -> dict[str, str]:
    path = Path(path)
    if not path.exists():
        return {}
    markets: dict[str, str] = {}
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            symbol = (row.get("symbol") or row.get("ticker") or "").strip()
            if symbol:
                markets[symbol] = (row.get("market") or "").strip().upper()
    return markets


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
    adjusted = (chart.get("indicators", {}).get("adjclose") or [{}])[0]
    adjusted_closes = adjusted.get("adjclose") or []

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
        adjusted_close = (
            adjusted_closes[idx]
            if idx < len(adjusted_closes) and adjusted_closes[idx] is not None
            else None
        )
        adjustment_factor = (
            float(adjusted_close) / float(values[3])
            if adjusted_close is not None and adjusted_close > 0 and values[3] > 0
            else None
        )
        rows.append(
            {
                "date": datetime.fromtimestamp(int(timestamp)).date().isoformat(),
                "symbol": symbol,
                "open": round(float(values[0]), 6),
                "high": round(float(values[1]), 6),
                "low": round(float(values[2]), 6),
                "close": round(float(values[3]), 6),
                "adjusted_open": round(float(values[0]) * adjustment_factor, 6) if adjustment_factor is not None else "",
                "adjusted_close": round(float(adjusted_close), 6) if adjustment_factor is not None else "",
                "volume": int(volumes[idx] or 0) if idx < len(volumes) else 0,
            }
        )
    if not rows:
        raise RuntimeError(f"{symbol}: no usable OHLC price rows")
    return rows


def _nasdaq_number(value: object) -> float | None:
    text = str(value or "").strip().replace("$", "").replace(",", "")
    if not text or text.upper() in {"N/A", "NA", "--"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def fetch_nasdaq_eod_price(
    symbol: str,
    start_date: date,
    end_date: date,
    timeout: int = 15,
) -> dict[str, str | float]:
    encoded_symbol = urllib.parse.quote(symbol, safe="")
    query = urllib.parse.urlencode(
        {
            "assetclass": "stocks",
            "fromdate": start_date.isoformat(),
            "todate": end_date.isoformat(),
            "limit": 20,
        }
    )
    url = f"https://api.nasdaq.com/api/quote/{encoded_symbol}/historical?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.nasdaq.com",
            "Referer": "https://www.nasdaq.com/",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    api_status = payload.get("status") or {}
    if api_status.get("rCode") not in (None, 200):
        raise RuntimeError(f"Nasdaq response code {api_status.get('rCode')}")
    api_rows = (((payload.get("data") or {}).get("tradesTable") or {}).get("rows") or [])
    parsed: list[dict[str, str | float]] = []
    for item in api_rows:
        try:
            candle_date = datetime.strptime(str(item.get("date") or ""), "%m/%d/%Y").date()
        except ValueError:
            continue
        open_value = _nasdaq_number(item.get("open"))
        high_value = _nasdaq_number(item.get("high"))
        low_value = _nasdaq_number(item.get("low"))
        close_value = _nasdaq_number(item.get("close"))
        volume_value = _nasdaq_number(item.get("volume"))
        if None in (open_value, high_value, low_value, close_value):
            continue
        parsed.append(
            {
                "date": candle_date.isoformat(),
                "symbol": symbol,
                "open": round(float(open_value), 6),
                "high": round(float(high_value), 6),
                "low": round(float(low_value), 6),
                "close": round(float(close_value), 6),
                "adjusted_open": round(float(open_value), 6),
                "adjusted_close": round(float(close_value), 6),
                "volume": int(volume_value or 0),
            }
        )
    if not parsed:
        raise RuntimeError("Nasdaq returned no usable EOD rows")
    return max(parsed, key=lambda row: str(row["date"]))


def _add_nasdaq_eod_fallback(
    rows: list[dict[str, str | float]],
    universe_path: str | Path,
    *,
    status_path: Path,
    output: Path,
    target_date: date,
    max_workers: int,
    request_timeout: int,
) -> dict[str, object]:
    markets = load_universe_markets(universe_path)
    latest_by_symbol: dict[str, str] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "")
        candle_date = str(row.get("date") or "")
        if symbol and candle_date > latest_by_symbol.get(symbol, ""):
            latest_by_symbol[symbol] = candle_date
    target_text = target_date.isoformat()
    stale_us = sorted(
        symbol for symbol, market in markets.items()
        if market == "US" and latest_by_symbol.get(symbol, "") < target_text
    )
    if not stale_us:
        return {"target_date": target_text, "symbols_requested": 0, "symbols_filled": 0, "rows_added": 0, "failed": []}

    start_date = target_date - timedelta(days=10)

    def download(symbol: str) -> tuple[str, dict[str, str | float] | None, str | None]:
        error = "unknown Nasdaq error"
        provider_symbols = [symbol]
        if "-" in symbol:
            provider_symbols.append(symbol.replace("-", "."))
        for attempt in range(2):
            for provider_symbol in provider_symbols:
                try:
                    row = fetch_nasdaq_eod_price(
                        provider_symbol,
                        start_date,
                        target_date,
                        timeout=max(15, request_timeout),
                    )
                    if str(row["date"]) < target_text:
                        raise RuntimeError(f"latest Nasdaq candle is {row['date']}")
                    row["symbol"] = symbol
                    return symbol, row, None
                except Exception as exc:  # noqa: BLE001
                    error = str(exc)
            if attempt == 0:
                time.sleep(0.35)
        return symbol, None, error

    filled: list[str] = []
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 6))) as executor:
        futures = [executor.submit(download, symbol) for symbol in stale_us]
        for processed, future in enumerate(as_completed(futures), start=1):
            symbol, fallback_row, error = future.result()
            if fallback_row is not None:
                rows.append(fallback_row)
                filled.append(symbol)
            else:
                failed.append(f"{symbol}: {error}")
            if processed % 25 == 0 or processed == len(stale_us):
                _write_status(
                    status_path,
                    "running",
                    symbols_requested=len(markets),
                    output=str(output),
                    nasdaq_target_date=target_text,
                    nasdaq_symbols_requested=len(stale_us),
                    nasdaq_symbols_processed=processed,
                    nasdaq_symbols_filled=len(filled),
                    nasdaq_failed_count=len(failed),
                )
    return {
        "target_date": target_text,
        "symbols_requested": len(stale_us),
        "symbols_filled": len(filled),
        "rows_added": len(filled),
        "filled_symbols": sorted(filled),
        "failed": failed,
    }


def update_prices_from_yahoo(
    universe_path: str | Path = DEFAULT_UNIVERSE,
    output_path: str | Path = DEFAULT_OUTPUT,
    range_value: str = "2y",
    interval: str = "1d",
    pause_seconds: float = 0.25,
    min_success_ratio: float = 0.97,
    # Three hours of lock meant a throttled run blocked every later attempt for
    # the rest of the morning; a run that has stopped moving is dead well before.
    stale_lock_minutes: int = 30,
    max_workers: int = 6,
    request_timeout: int = 12,
    nasdaq_fallback: bool = False,
    # request_timeout bounds one call, not the walk over 1,458 symbols. Without a
    # ceiling on the whole run, a throttling provider hangs the update
    # indefinitely while holding the lock.
    deadline_seconds: float = 900.0,
) -> DownloadSummary:
    symbols = load_universe(universe_path)
    if not symbols:
        raise RuntimeError(f"No symbols found in {Path(universe_path)}")

    output = Path(output_path)
    status_path = output.with_name(
        DEFAULT_STATUS.name if output.name == DEFAULT_OUTPUT.name else f"{output.stem}_update_status.json"
    )
    lock_path = output.with_name(f"{output.stem}_update.lock")
    _acquire_lock(lock_path, stale_lock_minutes)
    _write_status(status_path, "running", symbols_requested=len(symbols), output=str(output))

    rows: list[dict[str, str | float]] = []
    failed: list[str] = []
    try:
        def download(symbol: str) -> tuple[str, list[dict[str, str | float]], str | None]:
            try:
                downloaded = fetch_symbol_prices(symbol, range_value, interval, timeout=request_timeout)
                if not downloaded:
                    raise RuntimeError("No usable OHLC price rows")
                return symbol, downloaded, None
            except Exception as exc:  # noqa: BLE001
                return symbol, [], str(exc)

        processed = 0
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
            futures = [executor.submit(download, symbol) for symbol in symbols]
            try:
                for future in as_completed(futures, timeout=deadline_seconds or None):
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
            except TimeoutError as exc:
                for pending in futures:
                    pending.cancel()
                limit = deadline_seconds or 0
                spent = f"{limit / 60:.0f} นาที" if limit >= 60 else f"{limit:.0f} วินาที"
                raise PriceUpdateTimeout(
                    f"ดึงราคาไม่เสร็จภายใน {spent} "
                    f"(ได้ {processed} จาก {len(symbols)} รหัส) - "
                    "ผู้ให้บริการน่าจะกำลังจำกัดอัตรา ลองใหม่ภายหลัง"
                ) from exc

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
                    downloaded = fetch_symbol_prices(symbol, range_value, interval, timeout=max(20, request_timeout))
                    if not downloaded:
                        raise RuntimeError("No usable OHLC price rows")
                    rows.extend(downloaded)
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
        downloaded_rows = len(rows)
        retained_symbols = set()
        # A temporary provider failure must not erase the only stored history.
        # Retained symbols remain in the failure list and are never called fresh.
        if failed and output.exists():
            missing = {item.split(":", 1)[0] for item in failed}
            with output.open(encoding="utf-8-sig", newline="") as handle:
                for old_row in csv.DictReader(handle):
                    if old_row.get("symbol") in missing:
                        rows.append(old_row)
                        retained_symbols.add(old_row["symbol"])
        nasdaq_summary: dict[str, object] = {
            "symbols_requested": 0,
            "symbols_filled": 0,
            "rows_added": 0,
            "failed": [],
        }
        if nasdaq_fallback and interval == "1d":
            from .data_health import expected_eod_date

            nasdaq_summary = _add_nasdaq_eod_fallback(
                rows,
                universe_path,
                status_path=status_path,
                output=output,
                target_date=expected_eod_date(),
                max_workers=max_workers,
                request_timeout=request_timeout,
            )

        rows.sort(key=lambda row: (str(row["symbol"]), str(row["date"])))
        latest_candle_date = max(str(row["date"]) for row in rows)
        temp_output = output.with_name(f".{output.name}.{uuid4().hex}.tmp")
        with temp_output.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "date",
                    "symbol",
                    "open",
                    "high",
                    "low",
                    "close",
                    "adjusted_open",
                    "adjusted_close",
                    "volume",
                ],
            )
            writer.writeheader()
            writer.writerows(rows)
        temp_output.replace(output)

        metadata_path = output.with_name(f"{output.stem}_source.json")
        metadata = {
            "source": "Yahoo Finance + Nasdaq historical EOD fallback" if nasdaq_summary["rows_added"] else "Yahoo Finance",
            "range": range_value,
            "interval": interval,
            "updated_at": datetime.now(UTC).isoformat(),
            "latest_candle_date": latest_candle_date,
            "symbols_requested": len(symbols),
            "symbols_succeeded": succeeded,
            "rows_downloaded": downloaded_rows,
            "rows_stored": len(rows),
            "retained_symbols": sorted(retained_symbols),
            "failed": failed,
            "nasdaq_eod_fallback": nasdaq_summary,
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
