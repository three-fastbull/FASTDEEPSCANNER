from __future__ import annotations

import unittest

from fastdeep_scanner.financials import _add_ratios, _quarterly_by_year, _vi_summary


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


if __name__ == "__main__":
    unittest.main()
