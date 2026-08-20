from __future__ import annotations

import csv
import io
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from .data_io import data_source_label, load_market_data
from .financials import FinancialDataError, fetch_financials
from .models import ScanCriteria
from .report import build_report_html
from .scanner import scan_market

ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "fastdeep_web"


def _criteria_from_query(query: dict[str, list[str]]) -> ScanCriteria:
    pattern_value = query.get("patterns", [""])[0]
    patterns = tuple(item for item in pattern_value.split(",") if item) or ScanCriteria().patterns
    market = query.get("market", ["ALL"])[0] or "ALL"
    universe = query.get("universe", ["ALL"])[0] or "ALL"
    min_score = float(query.get("min_score", ["55"])[0] or 55)
    min_liquidity = float(query.get("min_liquidity", ["40"])[0] or 40)
    return ScanCriteria(
        market=market,
        universe=universe,
        patterns=patterns,
        min_score=min_score,
        min_liquidity=min_liquidity,
    )


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _tradingview_symbol(symbol: str, market: str) -> str:
    if market.upper() == "TH":
        return f"SET:{symbol.replace('.BK', '')}"
    if market.upper() == "CN":
        if symbol.endswith(".SS"):
            return f"SSE:{symbol.replace('.SS', '')}"
        if symbol.endswith(".SZ"):
            return f"SZSE:{symbol.replace('.SZ', '')}"
    return symbol


def _safe_print(message: str) -> None:
    if sys.stdout is None:
        return
    try:
        print(message)
    except OSError:
        return


class FastDeepHandler(BaseHTTPRequestHandler):
    server_version = "FastDeepScanner/1.0"

    def log_message(self, format: str, *args) -> None:
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        self._send(status, _json_bytes(payload), "application/json; charset=utf-8")

    def _serve_static(self, parsed_path: str) -> None:
        path = "index.html" if parsed_path in {"", "/"} else parsed_path.lstrip("/")
        target = (WEB_ROOT / path).resolve()
        if not str(target).startswith(str(WEB_ROOT.resolve())) or not target.exists():
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), content_type)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/scan":
            criteria = _criteria_from_query(query)
            results = scan_market(criteria)
            payload = {
                "generated_at": results[0].generated_at.isoformat() if results else "",
                "data_source": data_source_label(),
                "criteria": criteria.__dict__,
                "results": [result.to_dict() for result in results],
                "agents": [
                    "Market Scanner Agent",
                    "Financial Analysis Agent",
                    "Business Quality Agent",
                    "Technical Pattern Agent",
                    "Report Writer Agent",
                    "Presentation Agent",
                    "Content Agent",
                ],
            }
            self._send_json(payload)
            return

        if parsed.path == "/api/universe":
            from .data_io import load_universe_metadata

            universe = load_universe_metadata()
            self._send_json(
                {
                    "symbols": [
                        {"symbol": symbol, **metadata}
                        for symbol, metadata in sorted(universe.items())
                    ]
                }
            )
            return

        if parsed.path == "/api/financials":
            symbol = query.get("symbol", [""])[0]
            refresh = query.get("refresh", ["0"])[0].lower() in {"1", "true", "yes"}
            try:
                self._send_json(fetch_financials(symbol, refresh=refresh))
            except FinancialDataError as exc:
                self._send_json({"error": str(exc)}, 422)
            return

        if parsed.path == "/api/image-index":
            candles_by_symbol, fundamentals = load_market_data()
            payload = {
                "generated_at": "",
                "data_source": data_source_label(),
                "symbols": [
                    {
                        "symbol": symbol,
                        "name": fundamentals[symbol].name,
                        "market": fundamentals[symbol].market,
                        "sector": fundamentals[symbol].sector,
                        "index_groups": fundamentals[symbol].index_groups,
                        "tradingview_url": "https://www.tradingview.com/chart/?symbol="
                        + quote(_tradingview_symbol(symbol, fundamentals[symbol].market)),
                        "series": [
                            {"date": candle.date.isoformat(), "close": round(candle.close, 6)}
                            for candle in candles[-180:]
                        ],
                    }
                    for symbol, candles in candles_by_symbol.items()
                    if symbol in fundamentals
                ],
            }
            self._send_json(payload)
            return

        if parsed.path == "/api/symbol":
            symbol = query.get("symbol", [""])[0]
            criteria = _criteria_from_query(query)
            candles_by_symbol, fundamentals = load_market_data()
            results = {result.symbol: result for result in scan_market(criteria)}
            result = results.get(symbol)
            if result is None or symbol not in candles_by_symbol:
                self._send_json({"error": "symbol not found"}, 404)
                return
            snapshot = fundamentals[symbol]
            tv_symbol = quote(_tradingview_symbol(symbol, snapshot.market))
            self._send_json(
                {
                    "result": result.to_dict(),
                    "candles": [candle.to_dict() for candle in candles_by_symbol[symbol][-180:]],
                    "fundamental": snapshot.to_dict(),
                    "tradingview_url": f"https://www.tradingview.com/chart/?symbol={tv_symbol}",
                }
            )
            return

        if parsed.path == "/api/export.csv":
            criteria = _criteria_from_query(query)
            results = scan_market(criteria)
            output = io.StringIO()
            fieldnames = [
                "symbol",
                "name",
                "market",
                "sector",
                "last_price",
                "grade",
                "decision",
                "final_score",
                "technical_score",
                "fundamental_score",
                "business_score",
                "valuation_score",
                "patterns",
            ]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for result in results:
                row = result.to_dict()
                row["patterns"] = " | ".join(pattern.label for pattern in result.patterns)
                writer.writerow({key: row.get(key, "") for key in fieldnames})
            self._send(200, output.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8")
            return

        if parsed.path == "/api/report":
            symbol = query.get("symbol", [""])[0]
            criteria = _criteria_from_query(query)
            candles_by_symbol, fundamentals = load_market_data()
            results = {result.symbol: result for result in scan_market(criteria)}
            result = results.get(symbol)
            if result is None or symbol not in candles_by_symbol:
                self._send(404, b"Report not found", "text/plain; charset=utf-8")
                return
            body = build_report_html(result, candles_by_symbol[symbol], fundamentals[symbol]).encode("utf-8")
            self._send(200, body, "text/html; charset=utf-8")
            return

        self._serve_static(parsed.path)


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), FastDeepHandler)
    _safe_print(f"FastDeep Scanner running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _safe_print("FastDeep Scanner stopped")
    finally:
        server.server_close()
