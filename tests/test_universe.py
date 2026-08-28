from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from fastdeep_scanner.data_health import financial_data_health, price_data_health
from fastdeep_scanner.server import _tradingview_symbol
from fastdeep_scanner.universe import (
    FIELDS, GROUPS, merge_memberships, normalize_symbol, parse_csi, parse_ishares,
    parse_ssga, read_universe, universe_overview, update_universe, validate_members,
)
from fastdeep_scanner.yahoo_prices import update_prices_from_yahoo
from fastdeep_scanner.financials import cache_universe_financials


def member(symbol: str, market: str = "US", groups: str = "") -> dict[str, str]:
    return dict(symbol=symbol, name=symbol, market=market, sector="Unknown", index_groups=groups)


def write_universe(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


class UniverseTest(unittest.TestCase):
    def test_ishares_excludes_cash_funds_and_futures_and_preserves_share_classes(self):
        data = b'Fund Holdings as of,"Aug 26, 2026"\n\nTicker,Name,Asset Class,Sector,Market Currency\nBRK.B,Berkshire,Equity,Financials,USD\nGOOG,Alphabet,Equity,Communication,USD\nGOOGL,Alphabet A,Equity,Communication,USD\nUSD,Cash,Cash,Cash,USD\nXTSLA,Fund,Money Market,Cash,USD\nNQU6,Future,Futures,Cash,USD\n'
        stamp, rows = parse_ishares(data, "US")
        self.assertEqual(stamp, date(2026, 8, 26))
        self.assertEqual([row["symbol"] for row in rows], ["BRK-B", "GOOG", "GOOGL"])

    def test_hk_uses_hkd_counter_leading_zero_and_correct_tradingview(self):
        data = b'Fund Holdings as of,"27-Aug-2026"\nTicker,Name,Asset Class,Market Currency\n700,Tencent,Equity,HKD\n5,HSBC,Equity,HKD\n'
        _, rows = parse_ishares(data, "HK")
        self.assertEqual([row["symbol"] for row in rows], ["0700.HK", "0005.HK"])
        self.assertEqual(_tradingview_symbol("0700.HK", "HK"), "HKEX:700")
        self.assertEqual(normalize_symbol("09988", "HK"), "9988.HK")
        with self.assertRaises(ValueError):
            parse_ishares(data.replace(b"Equity,HKD", b"Equity,USD"), "HK")

    def test_ssga_ignores_cash_and_non_tradable_contingent_rights(self):
        import openpyxl
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.append(["Holdings:", "As of 26-Aug-2026"])
        sheet.append(["Name", "Ticker", "Identifier", "Shares Held", "Local Currency", "Sector"])
        sheet.append(["Apple", "AAPL", "037833100", 10, "USD", "Technology"])
        sheet.append(["US DOLLAR", "-", "999USDZ92", 100, "USD", "-"])
        sheet.append(["U.S. Dollar", "CASH_USD", "CASH_USD", 100, "USD", "-"])
        sheet.append(["CONTRA HOLOGIC INCORPO", "2602335D", "436CVR021", 10, "USD", "-"])
        output = io.BytesIO()
        book.save(output)
        book.close()
        stamp, rows = parse_ssga(output.getvalue())
        self.assertEqual(stamp, date(2026, 8, 26))
        self.assertEqual([row["symbol"] for row in rows], ["AAPL"])

    def test_csi_uses_exchange_and_string_code_not_index_name(self):
        from types import SimpleNamespace
        values = [["Date", "Index Code", "Index Name", "Index Name(Eng)", "Constituent Code", "Constituent Name", "Constituent Name(Eng)", "Exchange", "Exchange(Eng)"], ["20260827", "000300", "CSI", "CSI 300", "000001", "Ping An", "Ping An Bank", "SZ", "Shenzhen Stock Exchange"], ["20260827", "000300", "CSI", "CSI 300", "600519", "Moutai", "Kweichow Moutai", "SH", "Shanghai Stock Exchange"]]
        sheet = SimpleNamespace(nrows=len(values), row_values=lambda index: values[index])
        library = SimpleNamespace(open_workbook=lambda **kwargs: SimpleNamespace(sheet_by_index=lambda index: sheet))
        with patch("fastdeep_scanner.universe._library", return_value=library):
            stamp, rows = parse_csi(b"xls")
        self.assertEqual(stamp, date(2026, 8, 27))
        self.assertEqual([row["symbol"] for row in rows], ["000001.SZ", "600519.SS"])
        values[1][1] = "000905"
        with patch("fastdeep_scanner.universe._library", return_value=library), self.assertRaises(ValueError):
            parse_csi(b"xls")

    def test_rejects_future_stale_duplicate_and_incomplete_sources(self):
        rows = [member(f"{code:04d}.HK", "HK") for code in range(1, 31)]
        today = date(2026, 8, 28)
        validate_members("HSTECH", today, rows, today)
        for stamp, records in [(today + timedelta(days=10), rows), (today - timedelta(days=15), rows), (today, rows[:1]), (today, rows[:-1] + [rows[0]])]:
            with self.assertRaises(ValueError):
                validate_members("HSTECH", stamp, records, today)

    def test_merge_deduplicates_overlaps_preserves_custom_groups_and_removed_members(self):
        old = [member("AAA", groups="SP500|MY_LIST"), member("OLD", groups="SP500"), member("BBB", groups="NASDAQ100")]
        updated = merge_memberships(old, {"SP500": [member("BBB"), member("NEW")]})
        values = {row["symbol"]: row for row in updated}
        self.assertEqual(values["AAA"]["index_groups"], "MY_LIST")
        self.assertEqual(values["OLD"]["index_groups"], "WATCHLIST")
        self.assertEqual(values["BBB"]["index_groups"], "NASDAQ100|SP500")
        self.assertEqual(len(updated), 4)
        self.assertEqual(updated, merge_memberships(updated, {"SP500": [member("BBB"), member("NEW")]}))

    def test_download_failure_leaves_original_csv_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "universe.csv"
            write_universe(path, [member("AAA", groups="NASDAQ100")])
            original = path.read_bytes()
            def fail(url):
                raise OSError("Provider unavailable")
            result = update_universe(path, groups=("NASDAQ100",), fetcher=fail)
            self.assertIn("NASDAQ100", result["errors"])
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(path.with_suffix(".lock").exists())

    def test_dry_run_does_not_publish_and_success_creates_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data" / "universe.csv"
            path.parent.mkdir()
            write_universe(path, [member("AAA", groups="NASDAQ100")])
            original = path.read_bytes()
            with patch.dict(GROUPS["NASDAQ100"], {"bounds": (1, 2)}), patch("fastdeep_scanner.universe.parse_ishares", return_value=(date.today(), [member("AAA"), member("BBB")])):
                result = update_universe(path, groups=("NASDAQ100",), dry_run=True, fetcher=lambda url: b"fixture")
                self.assertEqual(result["after"], 2)
                self.assertEqual(path.read_bytes(), original)
                self.assertFalse(path.with_name("universe_source.json").exists())
                update_universe(path, groups=("NASDAQ100",), fetcher=lambda url: b"fixture")
            self.assertEqual(len(read_universe(path)), 2)
            self.assertEqual(len(list((Path(directory) / "storage" / "universe_backups").glob("*.csv"))), 1)

    def test_coverage_keeps_new_missing_symbols_in_all_denominators(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "universe.csv"
            write_universe(path, [member("AAA", groups="SP500|NASDAQ100"), member("BBB", groups="SP400"), member("0700.HK", "HK", "HSI|HSTECH")])
            prices = root / "prices.csv"
            prices.write_text("symbol,date,open,high,low,close,volume\nAAA,2026-08-27,1,1,1,1,1\nOUTSIDE,2026-08-27,1,1,1,1,1\n", encoding="utf-8")
            coverage = root / "coverage.json"
            coverage.write_text(json.dumps({"symbols_requested": 1, "cached_symbols": 1, "items": [{"symbol": "AAA", "status": "complete", "annual_complete": True}]}), encoding="utf-8")
            overview = universe_overview(path, price_path=prices, coverage_path=coverage, today=date(2026, 8, 28))
            self.assertEqual(overview["totals"]["registered"], 3)
            self.assertEqual(overview["totals"]["price_available"], 1)
            self.assertEqual(overview["totals"]["financial_complete"], 1)
            self.assertEqual(overview["totals"]["price_missing"], 2)
            health = price_data_health(prices, universe_path=path, status_path=root / "status.json", today=date(2026, 8, 28))
            self.assertEqual(health["symbols_requested"], 3)
            self.assertEqual(health["missing_count"], 2)
            self.assertFalse(health["can_publish"])
            financial = financial_data_health(root / "cache", universe_path=path, coverage_path=coverage, status_path=root / "status.json", sec_status_path=root / "sec.json")
            self.assertEqual(financial["symbols_requested"], 3)
            self.assertEqual(financial["missing_symbols"], 2)

    def test_failed_download_preserves_stored_history_without_claiming_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            universe, prices = root / "universe.csv", root / "prices.csv"
            write_universe(universe, [member("AAA"), member("BBB")])
            prices.write_text("date,symbol,open,high,low,close,volume\n2026-08-20,BBB,2,2,2,2,100\n", encoding="utf-8")
            def fetch(symbol, *args, **kwargs):
                return [dict(date="2026-08-27", symbol="AAA", open=1, high=1, low=1, close=1, volume=100)] if symbol == "AAA" else []
            with patch("fastdeep_scanner.yahoo_prices.fetch_symbol_prices", side_effect=fetch), patch("fastdeep_scanner.yahoo_prices.time.sleep"):
                result = update_prices_from_yahoo(universe, prices, pause_seconds=0, min_success_ratio=0.5)
            self.assertEqual(result.succeeded, 1)
            with prices.open(encoding="utf-8-sig", newline="") as handle:
                self.assertEqual({row["symbol"] for row in csv.DictReader(handle)}, {"AAA", "BBB"})
            source = json.loads(prices.with_name("prices_source.json").read_text(encoding="utf-8"))
            self.assertEqual(source["retained_symbols"], ["BBB"])
            self.assertEqual(len(source["failed"]), 1)

    def test_price_health_is_scoped_and_does_not_publish_an_empty_group(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            universe, prices = root / "universe.csv", root / "prices.csv"
            write_universe(universe, [member("AAA", groups="SP400"), member("OLD", groups="WATCHLIST")])
            prices.write_text("symbol,date,open,high,low,close,volume\nAAA,2026-08-27,1,1,1,1,1\nOLD,2026-08-20,1,1,1,1,1\n", encoding="utf-8")
            prices.with_name("prices_source.json").write_text(json.dumps({"failed": ["OLD: unavailable"]}), encoding="utf-8")
            kwargs = dict(universe_path=universe, status_path=root / "status.json", today=date(2026, 8, 28))
            self.assertFalse(price_data_health(prices, **kwargs)["can_publish"])
            current = price_data_health(prices, market="US", group="SP400", **kwargs)
            self.assertTrue(current["can_publish"])
            self.assertEqual(current["symbols_requested"], 1)
            self.assertEqual(current["failed_count"], 0)
            self.assertEqual(price_data_health(prices, group="WATCHLIST", **kwargs)["state"], "stale")
            self.assertFalse(price_data_health(prices, market="HK", group="SP400", **kwargs)["can_publish"])

    def test_financial_batch_filters_markets_and_does_not_force_yahoo_over_sec(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            universe = root / "universe.csv"
            write_universe(universe, [member("AAA", "US"), member("0700.HK", "HK")])
            with patch("fastdeep_scanner.financials.fetch_financials", return_value={"cache_status": "fresh"}) as fetch:
                result = cache_universe_financials(universe, markets=("HK",), cache_dir=root / "cache", coverage_path=root / "coverage.json", pause_seconds=0, max_retries=0)
            self.assertEqual(result["symbols"], 1)
            self.assertEqual(result["coverage"]["symbols_requested"], 2)
            self.assertEqual(fetch.call_args.args[0], "0700.HK")
            self.assertEqual(fetch.call_args.kwargs["provider"], "auto")

    def test_failed_sec_refresh_is_not_reported_as_fresh_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            universe = root / "universe.csv"
            write_universe(universe, [member("AAA")])
            with patch("fastdeep_scanner.financials.fetch_financials", return_value={"cache_status": "stale_verified", "refresh_error": "SEC unavailable"}):
                result = cache_universe_financials(universe, cache_dir=root / "cache", coverage_path=root / "coverage.json", pause_seconds=0, max_retries=0)
            self.assertEqual(result["succeeded"], [])
            self.assertEqual(result["failed"], ["AAA: SEC unavailable"])


if __name__ == "__main__":
    unittest.main()
