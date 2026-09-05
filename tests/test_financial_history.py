from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastdeep_scanner.financials import (
    CORE_ANNUAL_METRICS, METRIC_TYPES, _backfill_yahoo_annual, _extract_periods,
    _merge_period_metrics, _align_yahoo_quarters, fetch_financials,
)


def periods(years):
    return [{"period_end": f"{year}-12-31", "metrics": {key: year for key in CORE_ANNUAL_METRICS}} for year in years]


def yahoo_payload(years, currency="THB"):
    return {"timeseries": {"result": [
        {"annual" + METRIC_TYPES[metric]: [
            {"asOfDate": f"{year}-12-31", "periodType": "12M", "currencyCode": currency,
             "reportedValue": {"raw": year}} for year in years]}
        for metric in CORE_ANNUAL_METRICS
    ]}}


class YahooHistoryTest(unittest.TestCase):
    def test_historical_window_fills_fifth_year_without_overwriting_newer_figures(self):
        current = periods(range(2022, 2026))
        current[0]["metrics"]["total_revenue"] = 9000
        with patch("fastdeep_scanner.financials._download_json", return_value=yahoo_payload([2021, 2022])) as download:
            annual, metadata = _backfill_yahoo_annual("TEST.BK", current, "THB", 10)
        self.assertEqual(len(annual), 5)
        self.assertEqual(annual[1]["metrics"]["total_revenue"], 9000)
        self.assertEqual(metadata["annual_history_added"], ["2021-12-31"])
        self.assertNotIn("quarterly", download.call_args.args[0])

    def test_full_five_year_history_needs_no_extra_download(self):
        current = periods(range(2021, 2026))
        with patch("fastdeep_scanner.financials._download_json") as download:
            annual, _ = _backfill_yahoo_annual("TEST.BK", current, "THB", 10)
        self.assertEqual(annual, current)
        download.assert_not_called()

    def test_history_from_another_currency_is_not_merged(self):
        current = periods(range(2022, 2026))
        with patch("fastdeep_scanner.financials._download_json", return_value=yahoo_payload([2021], "USD")):
            annual, metadata = _backfill_yahoo_annual("TEST.BK", current, "THB", 10)
        self.assertEqual(annual, current)
        self.assertIn("annual_history_error", metadata)

    def test_failed_history_request_preserves_current_statements(self):
        current = periods(range(2022, 2026))
        with patch("fastdeep_scanner.financials._download_json", side_effect=OSError("unavailable")):
            annual, metadata = _backfill_yahoo_annual("TEST.BK", current, "THB", 10)
        self.assertEqual(annual, current)
        self.assertEqual(metadata["annual_history_error"], "unavailable")

    def test_semianual_values_are_not_called_one_quarter(self):
        payload = {"timeseries": {"result": [{"quarterlyTotalRevenue": [
            {"asOfDate": "2026-06-30", "periodType": "6M", "currencyCode": "HKD", "reportedValue": {"raw": 100}},
            {"asOfDate": "2026-03-31", "periodType": "3M", "currencyCode": "HKD", "reportedValue": {"raw": 40}},
        ]}]}}
        quarterly, _ = _extract_periods(payload, "quarterly")
        self.assertEqual([period["period_end"] for period in quarterly], ["2026-03-31"])

    def test_merge_preserves_history_and_missing_fields_but_new_values_win(self):
        older = periods([2021, 2022])
        newer = [{"period_end": "2022-12-31", "metrics": {"total_revenue": 5000}}]
        merged = _merge_period_metrics(older, newer)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[-1]["metrics"]["total_revenue"], 5000)
        self.assertEqual(merged[-1]["metrics"]["net_income"], 2022)
        self.assertEqual(older[-1]["metrics"]["total_revenue"], 2022)

    def test_later_refresh_does_not_drop_the_backfilled_year(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache / "TEST_BK.json").write_text(json.dumps({
                "symbol": "TEST.BK", "currency": "THB", "source": "Yahoo Finance fundamentals timeseries",
                "annual": periods(range(2021, 2026)), "quarterly_by_year": {}, "yahoo_history_version": 1,
            }), encoding="utf-8")
            with patch("fastdeep_scanner.financials._download_json", return_value=yahoo_payload(range(2022, 2026))) as download:
                with patch("fastdeep_scanner.financials.load_universe_metadata", return_value={}):
                    result = fetch_financials("TEST.BK", refresh=True, provider="yahoo", cache_dir=cache)
            self.assertEqual(len(result["annual"]), 5)
            self.assertEqual(result["annual"][0]["period_end"], "2021-12-31")
            self.assertEqual(download.call_count, 1)

    def test_merge_keeps_sources_for_metrics_only_in_older_statement(self):
        older = [{"period_end": "2021-12-31", "metrics": {"net_income": 10},
                  "metric_sources": {"net_income": {"kind": "reported"}}}]
        newer = [{"period_end": "2021-12-31", "metrics": {"total_revenue": 100},
                  "metric_sources": {"total_revenue": {"kind": "reported"}}}]
        merged = _merge_period_metrics(older, newer)
        self.assertEqual(set(merged[0]["metric_sources"]), {"net_income", "total_revenue"})
        self.assertEqual(set(older[0]["metric_sources"]), {"net_income"})

    def test_march_year_end_has_april_to_june_as_q1_not_q2(self):
        annual = [{"period_end": "2025-03-31"}, {"period_end": "2026-03-31"}]
        quarterly = [{"period_end": "2025-06-30", "metrics": {}},
                     {"period_end": "2025-12-31", "metrics": {}},
                     {"period_end": "2026-06-30", "metrics": {}}]
        aligned = _align_yahoo_quarters(quarterly, annual)
        self.assertEqual([(p["fiscal_year"], p["quarter"]) for p in aligned],
                         [("2026", "Q1"), ("2026", "Q3"), ("2027", "Q1")])

    def test_quarterly_eps_is_labeled_reported(self):
        payload = {"timeseries": {"result": [{"quarterlyBasicEPS": [
            {"asOfDate": "2025-12-31", "periodType": "3M", "currencyCode": "THB", "reportedValue": {"raw": 1.25}}
        ]}]}}
        quarterly, _ = _extract_periods(payload, "quarterly")
        self.assertEqual(quarterly[0]["metric_sources"]["basic_eps"]["kind"], "reported")


if __name__ == "__main__":
    unittest.main()
