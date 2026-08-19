from __future__ import annotations

import csv
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_UNIVERSE = ROOT / "data" / "fastdeep_universe.csv"
DEFAULT_OUTPUT = ROOT / "data" / "fastdeep_prices.csv"
DEFAULT_METADATA = ROOT / "data" / "fastdeep_prices_source.json"


@dataclass(frozen=True)
class DownloadSummary:
    symbols: int
    rows: int
    output: Path
    failed: list[str]


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


def fetch_symbol_prices(
    symbol: str,
    range_value: str = "2y",
    interval: str = "1d",
) -> list[dict[str, str | float]]:
    payload = _download_json(_chart_url(symbol, range_value, interval))
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
) -> DownloadSummary:
    symbols = load_universe(universe_path)
    if not symbols:
        raise RuntimeError(f"No symbols found in {Path(universe_path)}")

    rows: list[dict[str, str | float]] = []
    failed: list[str] = []
    for symbol in symbols:
        try:
            rows.extend(fetch_symbol_prices(symbol, range_value, interval))
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{symbol}: {exc}")
        time.sleep(pause_seconds)

    if not rows:
        raise RuntimeError("No price rows downloaded. Check network access or symbols.")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda row: (str(row["symbol"]), str(row["date"])))
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["date", "symbol", "open", "high", "low", "close", "volume"],
        )
        writer.writeheader()
        writer.writerows(rows)

    metadata_path = output.with_name(f"{output.stem}_source.json")
    metadata_path.write_text(
        json.dumps(
            {
                "source": "Yahoo Finance",
                "range": range_value,
                "interval": interval,
                "updated_at": datetime.now(UTC).isoformat(),
                "symbols_requested": len(symbols),
                "rows_downloaded": len(rows),
                "failed": failed,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return DownloadSummary(symbols=len(symbols), rows=len(rows), output=output, failed=failed)
