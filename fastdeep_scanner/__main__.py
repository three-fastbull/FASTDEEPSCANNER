from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import ScanCriteria
from .report import build_report_html
from .scanner import scan_market
from .data_io import load_market_data
from .server import run_server
from .static_export import export_static_dashboard
from .yahoo_prices import update_prices_from_yahoo


def _criteria(args: argparse.Namespace) -> ScanCriteria:
    patterns = tuple(args.patterns.split(",")) if args.patterns else ScanCriteria().patterns
    return ScanCriteria(
        market=args.market,
        universe=getattr(args, "universe", "ALL"),
        patterns=patterns,
        min_score=args.min_score,
        min_liquidity=args.min_liquidity,
    )


def scan_command(args: argparse.Namespace) -> None:
    results = scan_market(
        _criteria(args),
        market_data_path=args.market_data,
        fundamentals_path=args.fundamentals,
    )
    print(json.dumps([result.to_dict() for result in results], ensure_ascii=False, indent=2))


def report_command(args: argparse.Namespace) -> None:
    criteria = _criteria(args)
    candles_by_symbol, fundamentals = load_market_data(args.market_data, args.fundamentals)
    results = {result.symbol: result for result in scan_market(criteria, args.market_data, args.fundamentals)}
    result = results.get(args.symbol)
    if result is None:
        raise SystemExit(f"No scan result found for {args.symbol}")
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        build_report_html(result, candles_by_symbol[args.symbol], fundamentals[args.symbol]),
        encoding="utf-8",
    )
    print(f"wrote report: {output}")


def serve_command(args: argparse.Namespace) -> None:
    run_server(args.host, args.port)


def export_static_command(args: argparse.Namespace) -> None:
    output = export_static_dashboard(args.out, _criteria(args))
    print(f"wrote static dashboard: {output}")


def update_prices_command(args: argparse.Namespace) -> None:
    summary = update_prices_from_yahoo(
        universe_path=args.universe,
        output_path=args.out,
        range_value=args.range,
        interval=args.interval,
        pause_seconds=args.pause,
    )
    print(f"wrote prices: {summary.output}")
    print(f"- symbols requested: {summary.symbols}")
    print(f"- rows downloaded: {summary.rows}")
    if summary.failed:
        print("- failed:")
        for item in summary.failed:
            print(f"  - {item}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FastDeep stock scanner MVP")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Run scanner and print JSON")
    scan.add_argument("--market", default="ALL", choices=["ALL", "US", "TH", "CN"])
    scan.add_argument("--universe", default="ALL")
    scan.add_argument("--patterns", default="")
    scan.add_argument("--min-score", type=float, default=55)
    scan.add_argument("--min-liquidity", type=float, default=40)
    scan.add_argument("--market-data")
    scan.add_argument("--fundamentals")
    scan.set_defaults(func=scan_command)

    report = subparsers.add_parser("report", help="Create printable HTML report")
    report.add_argument("--symbol", required=True)
    report.add_argument("--out", default="storage/fastdeep_report.html")
    report.add_argument("--market", default="ALL", choices=["ALL", "US", "TH", "CN"])
    report.add_argument("--universe", default="ALL")
    report.add_argument("--patterns", default="")
    report.add_argument("--min-score", type=float, default=55)
    report.add_argument("--min-liquidity", type=float, default=40)
    report.add_argument("--market-data")
    report.add_argument("--fundamentals")
    report.set_defaults(func=report_command)

    serve = subparsers.add_parser("serve", help="Start web dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.set_defaults(func=serve_command)

    static = subparsers.add_parser("export-static", help="Create a standalone HTML dashboard")
    static.add_argument("--out", default="storage/fastdeep_static_dashboard.html")
    static.add_argument("--market", default="ALL", choices=["ALL", "US", "TH", "CN"])
    static.add_argument("--universe", default="ALL")
    static.add_argument("--patterns", default="")
    static.add_argument("--min-score", type=float, default=55)
    static.add_argument("--min-liquidity", type=float, default=40)
    static.set_defaults(func=export_static_command)

    update_prices = subparsers.add_parser(
        "update-prices",
        help="Download daily OHLCV prices from Yahoo Finance into data/fastdeep_prices.csv",
    )
    update_prices.add_argument("--universe", default="data/fastdeep_universe.csv")
    update_prices.add_argument("--out", default="data/fastdeep_prices.csv")
    update_prices.add_argument("--range", default="2y")
    update_prices.add_argument("--interval", default="1d")
    update_prices.add_argument("--pause", type=float, default=0.05)
    update_prices.set_defaults(func=update_prices_command)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
