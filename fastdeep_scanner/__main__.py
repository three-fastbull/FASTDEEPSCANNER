from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from .models import ScanCriteria
from .report import build_report_html
from .scanner import scan_market
from .data_io import load_market_data
from .data_health import price_data_health
from .backtest import run_event_study
from .financials import (
    audit_financial_cache,
    cache_sec_universe_financials,
    cache_universe_financials,
)
from .server import run_server
from .static_export import export_static_dashboard
from .yahoo_prices import update_prices_from_yahoo
from .timeframes import aggregate_candles


def _criteria(args: argparse.Namespace) -> ScanCriteria:
    patterns = tuple(args.patterns.split(",")) if args.patterns else ScanCriteria().patterns
    return ScanCriteria(
        market=args.market,
        universe=getattr(args, "universe", "ALL"),
        patterns=patterns,
        min_score=args.min_score,
        min_liquidity=args.min_liquidity,
        timeframe=getattr(args, "timeframe", "D"),
    )


def scan_command(args: argparse.Namespace) -> None:
    results = scan_market(
        _criteria(args),
        market_data_path=args.market_data,
        fundamentals_path=args.fundamentals,
    )
    print(json.dumps([result.to_dict() for result in results], ensure_ascii=True, indent=2))


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
        build_report_html(
            result,
            aggregate_candles(candles_by_symbol[args.symbol], criteria.timeframe),
            fundamentals[args.symbol],
        ),
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
        min_success_ratio=args.min_success_ratio,
        max_workers=args.workers,
        request_timeout=args.request_timeout,
    )
    print(f"wrote prices: {summary.output}")
    print(f"- symbols requested: {summary.symbols}")
    print(f"- symbols succeeded: {summary.succeeded}")
    print(f"- rows downloaded: {summary.rows}")
    print(f"- latest candle: {summary.latest_candle_date}")
    if summary.failed:
        print("- failed:")
        for item in summary.failed:
            print(f"  - {item}")


def update_financials_command(args: argparse.Namespace) -> None:
    summary = cache_universe_financials(
        args.universe,
        cache_dir=args.cache_dir,
        pause_seconds=args.pause,
        refresh=args.refresh,
        max_workers=args.workers,
        request_timeout=args.request_timeout,
        cache_max_age_hours=args.cache_max_age_hours,
        max_retries=args.retries,
        coverage_path=args.coverage_out,
    )
    print(f"cached financial statements: {len(summary['succeeded'])}/{summary['symbols']}")
    coverage = summary["coverage"]
    print(
        "coverage: "
        f"cached {coverage['cached_symbols']}/{coverage['symbols_requested']}, "
        f"annual 5y {coverage['annual_5y_symbols']}, "
        f"5y + Q1-Q4 {coverage['complete_symbols']}"
    )
    if summary["failed"]:
        print("- failed:")
        for item in summary["failed"]:
            print(f"  - {item}")


def update_sec_financials_command(args: argparse.Namespace) -> None:
    groups = tuple(value.strip() for value in args.groups.split(",") if value.strip())
    symbols = tuple(value.strip().upper() for value in args.symbols.split(",") if value.strip())
    try:
        summary = cache_sec_universe_financials(
            args.universe,
            cache_dir=args.cache_dir,
            groups=groups,
            symbols=symbols,
            pause_seconds=args.pause,
            refresh=args.refresh,
            request_timeout=args.request_timeout,
            cache_max_age_hours=args.cache_max_age_hours,
            max_retries=args.retries,
            limit=args.limit,
            coverage_path=args.coverage_out,
            ticker_cache_path=args.ticker_cache,
        )
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"SEC update unavailable: {exc}") from exc
    print(f"SEC statements: {len(summary['succeeded'])}/{summary['symbols']}")
    coverage = summary["coverage"]
    us_coverage = coverage.get("by_market", {}).get("US", {})
    print(
        "US coverage: "
        f"cached {us_coverage.get('cached', 0)}/{us_coverage.get('symbols', 0)}, "
        f"annual 5y {us_coverage.get('annual_5y', 0)}, "
        f"5y + Q1-Q4 {us_coverage.get('complete', 0)}"
    )
    if summary["failed"]:
        print("- failed:")
        for item in summary["failed"]:
            print(f"  - {item}")


def audit_financials_command(args: argparse.Namespace) -> None:
    report = audit_financial_cache(
        args.universe,
        cache_dir=args.cache_dir,
        output_path=args.out,
    )
    print(
        f"financial coverage: cached {report['cached_symbols']}/{report['symbols_requested']}, "
        f"annual 5y {report['annual_5y_symbols']}, "
        f"5y + Q1-Q4 {report['complete_symbols']}, "
        f"missing {report['missing_symbols']}"
    )


def daily_scan_command(args: argparse.Namespace) -> None:
    criteria = _criteria(args)
    results = scan_market(criteria)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "criteria": criteria.__dict__,
        "data_health": price_data_health(),
        "results": [result.to_dict() for result in results],
    }
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote daily scan: {output} ({len(results)} candidates)")


def backtest_command(args: argparse.Namespace) -> None:
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    horizons = tuple(int(value) for value in str(args.horizons).split(",") if value.strip())
    result = run_event_study(
        _criteria(args),
        horizons=horizons,
        cooldown_bars=args.cooldown_bars,
        cost_bps=args.cost_bps,
        max_symbols=args.max_symbols,
    )
    if args.summary_only:
        result = {key: value for key, value in result.items() if key != "events"}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote event study: {output} ({result['signals']} signals, {result['symbols_scanned']} symbols)")
    for row in result["by_pattern"]:
        headline = row.get(f"h{horizons[-1]}") or {}
        print(
            f"  {row['pattern']:<15} signals={row['signals']:<6} "
            f"hit={headline.get('hit_rate_pct', '-')}%  avg={headline.get('average_return_pct_net', '-')}%  "
            f"dd={headline.get('average_max_drawdown_pct', '-')}%"
        )


def update_filing_profiles_command(args: argparse.Namespace) -> None:
    from .filing_extract import update_filing_profiles
    from .financials import load_sec_ticker_map
    from .sec_edgar import lookup_cik_from_edgar

    universe = Path(args.universe)
    wanted = {value.strip().upper() for value in str(args.symbols).split(",") if value.strip()}
    groups = {value.strip().upper() for value in str(args.groups).split(",") if value.strip()}
    rows = list(csv.DictReader(universe.open("r", newline="", encoding="utf-8-sig")))
    ticker_map = load_sec_ticker_map(args.ticker_cache, timeout=args.request_timeout)

    targets: dict[str, str] = {}
    for row in rows:
        symbol = (row.get("symbol") or "").strip().upper()
        if not symbol or (row.get("market") or "").strip().upper() != "US":
            continue
        if wanted and symbol not in wanted:
            continue
        if groups and not groups & {
            item.strip().upper() for item in (row.get("index_groups") or "").split("|") if item.strip()
        }:
            continue
        identity = ticker_map.get(symbol.replace(".", "-"))
        cik = str(identity["cik"]) if identity else (lookup_cik_from_edgar(symbol) or "")
        if cik:
            targets[symbol] = cik
    if args.limit:
        targets = dict(list(targets.items())[: args.limit])

    summary = update_filing_profiles(
        targets,
        path=args.out,
        pause=args.pause,
        timeout=args.request_timeout,
        refresh=args.refresh,
    )
    print(
        f"filing profiles: {summary['succeeded']} new, {summary['skipped']} skipped, "
        f"{len(summary['failed'])} failed, {summary['stored']} stored"
    )
    for failure in summary["failed"][:10]:
        print(f"  - {failure}")


def summarize_filings_command(args: argparse.Namespace) -> None:
    from .summarize import SummaryError, summarize_all

    symbols = [value.strip() for value in str(args.symbols).split(",") if value.strip()]
    try:
        summary = summarize_all(
            symbols=symbols or None,
            path=args.store,
            model=args.model,
            pause=args.pause,
            timeout=args.request_timeout,
            refresh=args.refresh,
            limit=args.limit,
        )
    except SummaryError as exc:
        print(f"summaries: {exc}")
        raise SystemExit(1) from exc
    print(
        f"summaries: {summary['summarized']}/{summary['requested']} done, "
        f"{len(summary['failed'])} failed, {summary['with_thai']} companies now have Thai text"
    )
    for failure in summary["failed"][:10]:
        print(f"  - {failure}")


def update_fx_command(args: argparse.Namespace) -> None:
    from .yahoo_prices import update_fx_rates

    payload = update_fx_rates(args.out)
    print(f"wrote {len(payload['rates'])} FX rates to {args.out}; failed: {payload['failed'] or 'none'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FastDeep stock scanner MVP")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Run scanner and print JSON")
    scan.add_argument("--market", default="ALL", choices=["ALL", "US", "TH", "CN"])
    scan.add_argument("--universe", default="ALL")
    scan.add_argument("--patterns", default="")
    scan.add_argument("--min-score", type=float, default=70)
    scan.add_argument("--min-liquidity", type=float, default=40)
    scan.add_argument("--timeframe", default="D", choices=["D", "W", "M"])
    scan.add_argument("--market-data")
    scan.add_argument("--fundamentals")
    scan.set_defaults(func=scan_command)

    report = subparsers.add_parser("report", help="Create printable HTML report")
    report.add_argument("--symbol", required=True)
    report.add_argument("--out", default="storage/fastdeep_report.html")
    report.add_argument("--market", default="ALL", choices=["ALL", "US", "TH", "CN"])
    report.add_argument("--universe", default="ALL")
    report.add_argument("--patterns", default="")
    report.add_argument("--min-score", type=float, default=70)
    report.add_argument("--min-liquidity", type=float, default=40)
    report.add_argument("--timeframe", default="D", choices=["D", "W", "M"])
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
    static.add_argument("--min-score", type=float, default=70)
    static.add_argument("--min-liquidity", type=float, default=40)
    static.add_argument("--timeframe", default="D", choices=["D", "W", "M"])
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
    update_prices.add_argument("--min-success-ratio", type=float, default=0.97)
    update_prices.add_argument("--workers", type=int, default=6)
    update_prices.add_argument("--request-timeout", type=int, default=12)
    update_prices.set_defaults(func=update_prices_command)

    update_financials = subparsers.add_parser(
        "update-financials",
        help="Download and cache annual and quarterly financial statements for the universe",
    )
    update_financials.add_argument("--universe", default="data/fastdeep_universe.csv")
    update_financials.add_argument("--cache-dir", default="data/financial_cache")
    update_financials.add_argument("--pause", type=float, default=0.75)
    update_financials.add_argument("--refresh", action="store_true")
    update_financials.add_argument("--workers", type=int, default=1)
    update_financials.add_argument("--request-timeout", type=int, default=20)
    update_financials.add_argument("--cache-max-age-hours", type=int, default=168)
    update_financials.add_argument("--retries", type=int, default=2)
    update_financials.add_argument("--coverage-out", default="data/fastdeep_financial_coverage.json")
    update_financials.set_defaults(func=update_financials_command)

    update_sec = subparsers.add_parser(
        "update-sec-financials",
        help="Download SEC EDGAR 10-K/10-Q XBRL for US index constituents",
    )
    update_sec.add_argument("--universe", default="data/fastdeep_universe.csv")
    update_sec.add_argument("--cache-dir", default="data/financial_cache")
    update_sec.add_argument("--groups", default="SP500,NASDAQ100")
    update_sec.add_argument("--symbols", default="")
    update_sec.add_argument("--pause", type=float, default=0.20)
    update_sec.add_argument("--refresh", action="store_true")
    update_sec.add_argument("--request-timeout", type=int, default=30)
    update_sec.add_argument("--cache-max-age-hours", type=int, default=168)
    update_sec.add_argument("--retries", type=int, default=2)
    update_sec.add_argument("--limit", type=int, default=None)
    update_sec.add_argument("--coverage-out", default="data/fastdeep_financial_coverage.json")
    update_sec.add_argument("--ticker-cache", default="data/sec_company_tickers.json")
    update_sec.set_defaults(func=update_sec_financials_command)

    audit_financials = subparsers.add_parser(
        "audit-financials",
        help="Audit real 5-year and Q1-Q4 coverage without downloading data",
    )
    audit_financials.add_argument("--universe", default="data/fastdeep_universe.csv")
    audit_financials.add_argument("--cache-dir", default="data/financial_cache")
    audit_financials.add_argument("--out", default="data/fastdeep_financial_coverage.json")
    audit_financials.set_defaults(func=audit_financials_command)

    daily_scan = subparsers.add_parser("daily-scan", help="Write the daily EOD scan summary as JSON")
    daily_scan.add_argument("--out", default="storage/fastdeep_daily_scan_summary.json")
    daily_scan.add_argument("--market", default="ALL", choices=["ALL", "US", "TH", "CN"])
    daily_scan.add_argument("--universe", default="ALL")
    daily_scan.add_argument("--patterns", default="")
    daily_scan.add_argument("--min-score", type=float, default=70)
    daily_scan.add_argument("--min-liquidity", type=float, default=40)
    daily_scan.add_argument("--timeframe", default="D", choices=["D", "W", "M"])
    daily_scan.set_defaults(func=daily_scan_command)

    backtest = subparsers.add_parser("backtest", help="Run a historical pattern event study")
    backtest.add_argument("--out", default="storage/fastdeep_event_study.json")
    backtest.add_argument("--market", default="ALL", choices=["ALL", "US", "TH", "CN"])
    backtest.add_argument("--universe", default="ALL")
    backtest.add_argument("--patterns", default="breakout,retest,cup_handle,double_bottom,head_shoulders")
    backtest.add_argument("--min-score", type=float, default=70)
    backtest.add_argument("--min-liquidity", type=float, default=40)
    backtest.add_argument("--timeframe", default="D", choices=["D", "W", "M"])
    backtest.add_argument("--horizons", default="5,10,20", help="Forward holding periods in bars")
    backtest.add_argument("--cooldown-bars", type=int, default=20)
    backtest.add_argument("--cost-bps", type=float, default=30.0, help="Round-trip commission and slippage")
    backtest.add_argument("--max-symbols", type=int, default=None)
    backtest.add_argument("--summary-only", action="store_true", help="Drop the per-signal rows from the output")
    backtest.set_defaults(func=backtest_command)

    filing_profiles = subparsers.add_parser(
        "update-filing-profiles",
        help="Extract business text from each US company's latest annual SEC filing",
    )
    filing_profiles.add_argument("--universe", default="data/fastdeep_universe.csv")
    filing_profiles.add_argument("--out", default="data/fastdeep_filing_profiles.json")
    filing_profiles.add_argument("--groups", default="SP500,NASDAQ100")
    filing_profiles.add_argument("--symbols", default="")
    filing_profiles.add_argument("--pause", type=float, default=0.2)
    filing_profiles.add_argument("--request-timeout", type=int, default=60)
    filing_profiles.add_argument("--ticker-cache", default="data/sec_company_tickers.json")
    filing_profiles.add_argument("--refresh", action="store_true")
    filing_profiles.add_argument("--limit", type=int, default=None)
    filing_profiles.set_defaults(func=update_filing_profiles_command)

    summarize = subparsers.add_parser(
        "summarize-filings",
        help="Translate and condense the stored filing text into Thai with the Claude API",
    )
    summarize.add_argument("--store", default="data/fastdeep_filing_profiles.json")
    summarize.add_argument("--symbols", default="")
    summarize.add_argument("--model", default="claude-haiku-4-5-20251001")
    summarize.add_argument("--pause", type=float, default=0.3)
    summarize.add_argument("--request-timeout", type=int, default=60)
    summarize.add_argument("--refresh", action="store_true")
    summarize.add_argument("--limit", type=int, default=None)
    summarize.set_defaults(func=summarize_filings_command)

    update_fx = subparsers.add_parser("update-fx", help="Refresh currency rates used for valuation and liquidity")
    update_fx.add_argument("--out", default="data/fastdeep_fx_rates.json")
    update_fx.set_defaults(func=update_fx_command)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
