from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastdeep_scanner.financials import (
    _add_ratios,
    _quarterly_by_year,
    _vi_summary,
    assess_financial_payload,
    audit_financial_cache,
)


class FinancialDataTest(unittest.TestCase):
    def setUp(self) -> None:
        self.annual = [
            {
                "period_end": "2023-12-31",
                "metrics": {
                    "total_revenue": 1000,
                    "gross_profit": 400,
                    "net_income": 100,
                    "total_assets": 1500,
                    "stockholders_equity": 500,
                    "total_debt": 250,
                    "free_cash_flow": 80,
                },
            },
            {
                "period_end": "2024-12-31",
                "metrics": {
                    "total_revenue": 1200,
                    "gross_profit": 540,
                    "net_income": 150,
                    "total_assets": 1800,
                    "stockholders_equity": 600,
                    "total_debt": 240,
                    "free_cash_flow": 130,
                },
            },
        ]

    def test_add_ratios_uses_average_balance_sheet_values(self) -> None:
        ratios = _add_ratios(self.annual)
        self.assertAlmostEqual(ratios[-1]["ratios"]["roe"], 150 / 550 * 100)
        self.assertAlmostEqual(ratios[-1]["ratios"]["roa"], 150 / 1650 * 100)
        self.assertAlmostEqual(ratios[-1]["ratios"]["debt_to_equity"], 0.4)

    def test_missing_q4_is_derived_from_annual_flow_values(self) -> None:
        quarterly = [
            {"period_end": "2024-03-31", "metrics": {"total_revenue": 250, "total_assets": 1600}},
            {"period_end": "2024-06-30", "metrics": {"total_revenue": 280, "total_assets": 1650}},
            {"period_end": "2024-09-30", "metrics": {"total_revenue": 300, "total_assets": 1700}},
        ]
        grouped = _quarterly_by_year(quarterly, self.annual)
        q4 = next(item for item in grouped["2024"] if item["quarter"] == "Q4")
        self.assertTrue(q4["derived_from_annual"])
        self.assertEqual(q4["metrics"]["total_revenue"], 370)
        self.assertEqual(q4["metrics"]["total_assets"], 1800)

    def test_vi_summary_reports_growth_period(self) -> None:
        summary = _vi_summary(_add_ratios(self.annual))
        self.assertTrue(summary["available"])
        self.assertEqual(summary["period"], "2023-2024")
        revenue = next(item for item in summary["checks"] if item["key"] == "revenue")
        self.assertAlmostEqual(revenue["cagr"], 20.0)

    def test_vi_summary_does_not_emit_complex_cagr_for_a_new_loss(self) -> None:
        annual = [
            {"period_end": "2023-12-31", "metrics": {"total_revenue": 100, "net_income": 10}},
            {"period_end": "2024-12-31", "metrics": {"total_revenue": -20, "net_income": -5}},
        ]
        summary = _vi_summary(_add_ratios(annual))
        revenue = next(item for item in summary["checks"] if item["key"] == "revenue")
        profit = next(item for item in summary["checks"] if item["key"] == "net_income")
        self.assertIsNone(revenue["cagr"])
        self.assertIsNone(profit["cagr"])

    def test_coverage_does_not_call_a_four_year_cache_complete(self) -> None:
        annual = []
        quarterly = {}
        for year in range(2022, 2026):
            annual.append(
                {
                    "period_end": f"{year}-12-31",
                    "metrics": {metric: 100 for metric in (
                        "total_revenue",
                        "net_income",
                        "total_assets",
                        "total_liabilities",
                        "stockholders_equity",
                    )},
                }
            )
            quarterly[str(year)] = [
                {"quarter": f"Q{quarter}", "metrics": {"total_revenue": 25}}
                for quarter in range(1, 5)
            ]
        quality = assess_financial_payload({"annual": annual, "quarterly_by_year": quarterly})
        self.assertEqual(quality["status"], "partial")
        self.assertFalse(quality["annual_complete"])

    def test_coverage_requires_five_full_quarter_years(self) -> None:
        annual = []
        quarterly = {}
        for year in range(2021, 2026):
            annual.append(
                {
                    "period_end": f"{year}-12-31",
                    "metrics": {metric: 100 for metric in (
                        "total_revenue",
                        "net_income",
                        "total_assets",
                        "total_liabilities",
                        "stockholders_equity",
                    )},
                }
            )
            quarterly[str(year)] = [
                {"quarter": f"Q{quarter}", "metrics": {"total_revenue": 25}}
                for quarter in range(1, 5)
            ]
        quality = assess_financial_payload({"annual": annual, "quarterly_by_year": quarterly})
        self.assertEqual(quality["status"], "complete")
        self.assertEqual(quality["annual_periods"], 5)
        self.assertEqual(len(quality["full_quarter_years"]), 5)

    def test_cache_audit_keeps_missing_symbols_in_the_denominator(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            universe = root / "universe.csv"
            universe.write_text(
                "symbol,name,market,sector,index_groups\nAAA,Alpha,US,Tech,TEST\nBBB,Beta,TH,Bank,TEST\n",
                encoding="utf-8",
            )
            cache = root / "cache"
            cache.mkdir()
            annual = []
            quarterly = {}
            for year in range(2021, 2026):
                annual.append(
                    {
                        "period_end": f"{year}-12-31",
                        "metrics": {metric: 100 for metric in (
                            "total_revenue",
                            "net_income",
                            "total_assets",
                            "total_liabilities",
                            "stockholders_equity",
                        )},
                    }
                )
                quarterly[str(year)] = [
                    {"quarter": f"Q{quarter}", "metrics": {"total_revenue": 25}}
                    for quarter in range(1, 5)
                ]
            (cache / "AAA.json").write_text(
                json.dumps({"symbol": "AAA", "annual": annual, "quarterly_by_year": quarterly}),
                encoding="utf-8",
            )
            report = audit_financial_cache(
                universe,
                cache_dir=cache,
                output_path=root / "coverage.json",
            )
            self.assertEqual(report["symbols_requested"], 2)
            self.assertEqual(report["complete_symbols"], 1)
            self.assertEqual(report["missing_symbols"], 1)


if __name__ == "__main__":
    unittest.main()
