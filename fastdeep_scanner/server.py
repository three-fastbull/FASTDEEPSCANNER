from __future__ import annotations

import csv
import io
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from .data_health import (
    financial_data_health,
    fx_health,
    price_data_health,
    symbol_freshness,
)
from .data_io import completed_eod_candles, data_source_label, load_market_data
from .financials import FinancialDataError, fetch_financials
from .hall_of_fame import build_hall_of_fame
from .models import ScanCriteria
from .report import build_report_html
from .currency import load_fx_rates
from .research_journal import MOAT_VALUES, STATUSES, TREND_VALUES, get_research, save_research
from .scanner import VERIFICATION_LABELS, scan_market
from .stock_profile import build_stock_profile
from .timeframes import aggregate_candles, normalize_timeframe
from .trade_journal import close_trade, journal_summary, list_trades, open_trade
from .universe import universe_overview

ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "fastdeep_web"


def _criteria_from_query(query: dict[str, list[str]]) -> ScanCriteria:
    pattern_value = query.get("patterns", [""])[0]
    patterns = tuple(item for item in pattern_value.split(",") if item) or ScanCriteria().patterns
    market = query.get("market", ["ALL"])[0] or "ALL"
    universe = query.get("universe", ["ALL"])[0] or "ALL"
    min_score = float(query.get("min_score", ["70"])[0] or 70)
    min_liquidity = float(query.get("min_liquidity", ["40"])[0] or 40)
    try:
        timeframe = normalize_timeframe(query.get("timeframe", ["D"])[0] or "D")
    except ValueError:
        timeframe = "D"
    return ScanCriteria(
        market=market,
        universe=universe,
        patterns=patterns,
        min_score=min_score,
        min_liquidity=min_liquidity,
        timeframe=timeframe,
    )


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _tradingview_symbol(symbol: str, market: str) -> str:
    if symbol.upper().endswith(".HK") and symbol[:-3].isdigit():
        return f"HKEX:{int(symbol[:-3])}"
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
        self.send_header("Cache-Control", "no-store")
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
            health = price_data_health(market=criteria.market, group=criteria.universe)
            verification_counts: dict[str, int] = {key: 0 for key in VERIFICATION_LABELS}
            for result in results:
                verification_counts[result.verification_level] = (
                    verification_counts.get(result.verification_level, 0) + 1
                )
            payload = {
                "generated_at": results[0].generated_at.isoformat() if results else "",
                "data_source": data_source_label(),
                "data_health": health,
                "financial_health": financial_data_health(),
                "symbol_freshness": symbol_freshness(),
                "fx_health": fx_health(),
                "verification_counts": verification_counts,
                "verification_labels": VERIFICATION_LABELS,
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

        if parsed.path == "/api/data-health":
            self._send_json(
                {
                    "prices": price_data_health(),
                    "financials": financial_data_health(),
                    "symbols": symbol_freshness(),
                    "fx": fx_health(),
                }
            )
            return

        if parsed.path == "/api/hall-of-fame":
            try:
                minimum = max(0.0, min(1000.0, float(query.get("min_return", ["15"])[0] or 15)))
            except ValueError:
                minimum = 15.0
            self._send_json(
                build_hall_of_fame(
                    min_return=minimum,
                    market=(query.get("market", ["ALL"])[0] or "ALL"),
                    universe=(query.get("universe", ["ALL"])[0] or "ALL"),
                )
            )
            return

        if parsed.path == "/api/stock-profile":
            symbol = (query.get("symbol", [""])[0] or "").strip().upper()
            candles_by_symbol, fundamentals = load_market_data()
            if symbol not in candles_by_symbol or symbol not in fundamentals:
                self._send_json({"error": f"ไม่พบหุ้น {symbol} ในฐานข้อมูล"}, 404)
                return
            try:
                financials = fetch_financials(symbol)
            except FinancialDataError:
                financials = None
            self._send_json(
                build_stock_profile(
                    symbol,
                    financials,
                    completed_eod_candles(candles_by_symbol[symbol]),
                    fundamentals[symbol],
                    get_research(symbol),
                    load_fx_rates().get("rates", {}),
                )
            )
            return

        if parsed.path == "/api/research-options":
            self._send_json(
                {
                    "statuses": sorted(STATUSES),
                    "moat": sorted(MOAT_VALUES),
                    "ai_trend": sorted(TREND_VALUES),
                }
            )
            return

        if parsed.path == "/api/trades":
            self._send_json({"trades": list_trades(), "summary": journal_summary()})
            return

        if parsed.path == "/api/screener":
            from .screener import build_screener

            market = (query.get("market", ["US"])[0] or "US").upper()
            self._send_json(build_screener(market=market))
            return

        if parsed.path == "/api/event-study":
            timeframe = (query.get("timeframe", ["D"])[0] or "D").upper()
            study_path = ROOT / "storage" / f"fastdeep_event_study_{timeframe}.json"
            if not study_path.exists():
                self._send_json({"error": f"ยังไม่มีผล event study ของ timeframe {timeframe}"}, 404)
                return
            try:
                study = json.loads(study_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self._send_json({"error": str(exc)}, 500)
                return
            study.pop("events", None)
            self._send_json(study)
            return

        if parsed.path == "/api/universe":
            self._send_json(universe_overview())
            return

        if parsed.path == "/api/financials":
            symbol = query.get("symbol", [""])[0]
            refresh = query.get("refresh", ["0"])[0].lower() in {"1", "true", "yes"}
            try:
                self._send_json(fetch_financials(symbol, refresh=refresh))
            except FinancialDataError as exc:
                self._send_json({"error": str(exc)}, 422)
            return

        if parsed.path == "/api/research":
            self._send_json(get_research(query.get("symbol", [""])[0]))
            return

        if parsed.path == "/api/image-index":
            candles_by_symbol, fundamentals = load_market_data()
            payload = {
                "generated_at": "",
                "data_source": data_source_label(),
                "data_health": price_data_health(),
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
                            for candle in completed_eod_candles(candles)[-180:]
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
                    "candles": [
                        candle.to_dict()
                        for candle in completed_eod_candles(candles_by_symbol[symbol])[-180:]
                    ],
                    "fundamental": snapshot.to_dict(),
                    "tradingview_url": f"https://www.tradingview.com/chart/?symbol={tv_symbol}",
                    "data_health": price_data_health(market=criteria.market, group=criteria.universe),
                }
            )
            return

        if parsed.path == "/api/export.csv":
            criteria = _criteria_from_query(query)
            health = price_data_health(market=criteria.market, group=criteria.universe)
            if not health["can_publish"]:
                self._send_json(
                    {"error": health["message"], "data_health": health},
                    409,
                )
                return
            results = scan_market(criteria)
            output = io.StringIO()
            fieldnames = [
                "symbol",
                "name",
                "market",
                "sector",
                "currency",
                "last_price",
                "price_as_of",
                "grade",
                "decision",
                "verification_level",
                "final_score",
                "score_cap",
                "technical_score",
                "fundamental_score",
                "business_score",
                "valuation_score",
                "reporting_currency",
                "liquidity_score",
                "turnover_usd",
                "research_status",
                "entry",
                "stop",
                "patterns",
            ]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for result in results:
                row = result.to_dict()
                row["patterns"] = " | ".join(pattern.label for pattern in result.patterns)
                row["entry"] = result.risk_plan.entry
                row["stop"] = result.risk_plan.stop
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
            body = build_report_html(
                result,
                aggregate_candles(completed_eod_candles(candles_by_symbol[symbol]), criteria.timeframe),
                fundamentals[symbol],
                data_health=price_data_health(market=criteria.market, group=criteria.universe),
            ).encode("utf-8")
            self._send(200, body, "text/html; charset=utf-8")
            return

        self._serve_static(parsed.path)

    def _read_json_body(self) -> dict:
        size = int(self.headers.get("Content-Length", "0"))
        if size <= 0:
            return {}
        return json.loads(self.rfile.read(size).decode("utf-8"))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        routes = {
            "/api/research": self._post_research,
            "/api/trades": self._post_trade,
            "/api/trades/close": self._post_trade_close,
        }
        handler = routes.get(parsed.path)
        if handler is None:
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        try:
            handler(self._read_json_body())
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, 422)

    def _post_research(self, payload: dict) -> None:
        item = save_research(
            str(payload.get("symbol") or ""),
            str(payload.get("status") or "Watch"),
            str(payload.get("note") or ""),
            moat=str(payload.get("moat") or ""),
            ai_trend=str(payload.get("ai_trend") or ""),
            fair_value=payload.get("fair_value"),
            thesis=str(payload.get("thesis") or ""),
            business_summary=payload.get("business_summary"),
            revenue_model=payload.get("revenue_model"),
            revenue_segments=payload.get("revenue_segments"),
            key_customers=payload.get("key_customers"),
            competitors=payload.get("competitors"),
            moat_evidence=payload.get("moat_evidence"),
            catalysts=payload.get("catalysts"),
            risks=payload.get("risks"),
            invalidation=payload.get("invalidation"),
            source_urls=payload.get("source_urls"),
        )
        self._send_json(item)

    def _post_trade(self, payload: dict) -> None:
        trade = open_trade(
            str(payload.get("symbol") or ""),
            entry=payload.get("entry"),
            stop=payload.get("stop"),
            targets=payload.get("targets") or [],
            side=str(payload.get("side") or "BUY"),
            timeframe=str(payload.get("timeframe") or "D"),
            pattern=str(payload.get("pattern") or ""),
            grade=str(payload.get("grade") or ""),
            currency=str(payload.get("currency") or ""),
            note=str(payload.get("note") or ""),
        )
        self._send_json({"trade": trade, "summary": journal_summary()})

    def _post_trade_close(self, payload: dict) -> None:
        trade = close_trade(
            str(payload.get("id") or ""),
            exit_price=payload.get("exit_price"),
            note=str(payload.get("note") or ""),
        )
        self._send_json({"trade": trade, "summary": journal_summary()})


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), FastDeepHandler)
    _safe_print(f"FastDeep Scanner running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _safe_print("FastDeep Scanner stopped")
    finally:
        server.server_close()
