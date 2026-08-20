from __future__ import annotations

import unittest
from datetime import date, timedelta

from fastdeep_scanner.financials import _add_ratios, _quarterly_by_year, assess_financial_payload
from fastdeep_scanner.sec_edgar import normalize_companyfacts


class SecEdgarTest(unittest.TestCase):
    def _payload(self) -> dict:
        facts: dict = {"us-gaap": {}}

        def add(concept: str, unit: str, item: dict) -> None:
            node = facts["us-gaap"].setdefault(concept, {"units": {}})
            node["units"].setdefault(unit, []).append(item)

        concepts = {
            "RevenueFromContractWithCustomerExcludingAssessedTax": 1_000.0,
            "NetIncomeLoss": 100.0,
            "Assets": 2_000.0,
            "Liabilities": 1_200.0,
            "StockholdersEquity": 800.0,
            "NetCashProvidedByUsedInOperatingActivities": 180.0,
            "PaymentsToAcquirePropertyPlantAndEquipment": 50.0,
        }
        for year in range(2021, 2026):
            annual_end = date(year, 12, 31)
            for concept, value in concepts.items():
                item = {
                    "end": annual_end.isoformat(),
                    "val": value + (year - 2021) * 10,
                    "accn": f"0000000000-{year % 100:02d}-000001",
                    "fy": year,
                    "fp": "FY",
                    "form": "10-K",
                    "filed": (annual_end + timedelta(days=60)).isoformat(),
                }
                if concept not in {"Assets", "Liabilities", "StockholdersEquity"}:
                    item["start"] = date(year, 1, 1).isoformat()
                add(concept, "USD", item)

            for quarter, (month, day) in enumerate(((3, 31), (6, 30), (9, 30)), start=1):
                quarter_end = date(year, month, day)
                for concept, annual_value in concepts.items():
                    is_balance = concept in {"Assets", "Liabilities", "StockholdersEquity"}
                    is_cash_flow = concept in {
                        "NetCashProvidedByUsedInOperatingActivities",
                        "PaymentsToAcquirePropertyPlantAndEquipment",
                    }
                    value = annual_value / 10 * quarter
                    item = {
                        "end": quarter_end.isoformat(),
                        "val": value,
                        "accn": f"0000000000-{year % 100:02d}-00000{quarter + 1}",
                        "fy": year,
                        "fp": f"Q{quarter}",
                        "form": "10-Q",
                        "filed": (quarter_end + timedelta(days=40)).isoformat(),
                    }
                    if not is_balance:
                        item["start"] = (
                            date(year, 1, 1) if is_cash_flow else date(year, month - 2, 1)
                        ).isoformat()
                    add(concept, "USD", item)

        return {"entityName": "Example Corp", "facts": facts}

    def test_normalizes_five_years_and_derives_discrete_cash_flow(self) -> None:
        normalized = normalize_companyfacts(
            self._payload(),
            symbol="TEST",
            cik="0000000001",
        )
        self.assertEqual(normalized["currency"], "USD")
        self.assertEqual(len(normalized["annual"]), 5)
        year_2025 = {
            item["quarter"]: item
            for item in normalized["quarterly"]
            if item["fiscal_year"] == "2025"
        }
        self.assertEqual(year_2025["Q2"]["metrics"]["operating_cash_flow"], 18.0)

    def test_sec_periods_pass_strict_five_year_quarter_audit(self) -> None:
        normalized = normalize_companyfacts(
            self._payload(),
            symbol="TEST",
            cik="0000000001",
        )
        annual = _add_ratios(normalized["annual"][-5:])
        quarterly_by_year = _quarterly_by_year(normalized["quarterly"], annual)
        quality = assess_financial_payload(
            {"annual": annual, "quarterly_by_year": quarterly_by_year}
        )
        self.assertEqual(quality["status"], "complete")
        self.assertEqual(len(quality["full_quarter_years"]), 5)
        q4 = next(item for item in quarterly_by_year["2025"] if item["quarter"] == "Q4")
        self.assertTrue(q4["derived_from_annual"])


if __name__ == "__main__":
    unittest.main()
