from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from fastdeep_scanner.financials import (
    _build_financial_payload, _quarterly_by_year, _with_currency_presentation,
    assess_financial_payload,
)
from fastdeep_scanner.sec_edgar import normalize_companyfacts


def fact(start, end, value, *, fy=None, fp="FY", form="10-K", filed=None, accession=None):
    result = {
        "end": end, "val": value, "fy": fy or int(end[:4]), "fp": fp, "form": form,
        "filed": filed or f"{int(end[:4]) + 1}-03-01",
        "accn": accession or f"0000000001-{end[:4]}-{fp}",
    }
    if start:
        result["start"] = start
    return result


def company(annual, quarterly=(), cash=(), eps=()):
    income = list(annual) + list(quarterly)
    instants = [{key: value for key, value in item.items() if key != "start"} for item in income]
    nodes = {
        "Revenues": income, "NetIncomeLoss": income,
        "Assets": instants, "Liabilities": instants, "StockholdersEquity": instants,
        "NetCashProvidedByUsedInOperatingActivities": list(cash),
    }
    payload = {"cik": 1, "entityName": "Test issuer", "facts": {"us-gaap": {
        concept: {"units": {"USD": copy.deepcopy(items)}} for concept, items in nodes.items()
    }}}
    payload["facts"]["us-gaap"]["EarningsPerShareBasic"] = {"units": {"USD/shares": list(eps)}}
    return payload


def normalized(payload):
    return normalize_companyfacts(payload, symbol="TEST", cik="0000000001")


class SecPeriodNormalizationTest(unittest.TestCase):
    def test_current_reporting_currency_wins_over_longer_old_history(self):
        payload = company([fact("2025-01-01", "2025-12-31", 100)])
        for concept in ("Revenues", "NetIncomeLoss", "Assets"):
            payload["facts"]["us-gaap"][concept]["units"]["RUB"] = [
                fact("2020-01-01", "2020-12-31", 500)] * 30
        result = normalized(payload)
        self.assertEqual(result["currency"], "USD")
        self.assertEqual(result["annual"][-1]["period_end"], "2025-12-31")
        self.assertEqual(result["annual"][-1]["metrics"]["total_revenue"], 100)

    def test_transition_statement_is_flagged_not_presented_as_twelve_months(self):
        payload = company([fact("2023-11-01", "2024-10-31", 100),
                           fact("2024-11-01", "2025-09-30", 90, form="10-KT")])
        result = normalized(payload)
        self.assertEqual(result["annual"][-1]["period_end"], "2024-10-31")
        self.assertEqual(result["excluded_periods"][0]["period_end"], "2025-09-30")
        self.assertEqual(result["excluded_periods"][0]["source_form"], "10-KT")

    def test_comparatives_are_kept_in_the_year_of_the_fact(self):
        annual = [fact(f"{year}-01-01", f"{year}-12-31", year, fy=2025,
                       filed="2026-03-01", accession="0000000001-26-000001")
                  for year in (2023, 2024, 2025)]
        result = normalized(company(annual))
        self.assertEqual([p["fiscal_year"] for p in result["annual"]], ["2023", "2024", "2025"])
        self.assertEqual(result["annual"][0]["metrics"]["net_income"], 2023)

    def test_instant_in_annual_report_is_not_an_annual_statement(self):
        annual = [fact("2025-01-01", "2025-12-31", 100)]
        payload = company(annual)
        for concept in ("Assets", "Liabilities", "StockholdersEquity"):
            payload["facts"]["us-gaap"][concept]["units"]["USD"].append(
                fact(None, "2025-06-30", 90, filed="2026-03-01"))
        self.assertEqual([p["period_end"] for p in normalized(payload)["annual"]], ["2025-12-31"])

    def test_wrong_filing_year_does_not_duplicate_fiscal_year(self):
        annual = [fact(f"{year}-01-01", f"{year}-12-31", 100,
                       fy=2020 if year == 2021 else year) for year in range(2021, 2026)]
        self.assertEqual([p["fiscal_year"] for p in normalized(company(annual))["annual"]],
                         [str(year) for year in range(2021, 2026)])

    def test_non_calendar_fiscal_year_uses_issuer_convention(self):
        annual = [fact(f"{year - 1}-03-01", f"{year}-02-28", 100,
                       fy=year if year == 2022 else year - 1,
                       filed=f"{year}-04-30") for year in range(2022, 2026)]
        self.assertEqual([p["fiscal_year"] for p in normalized(company(annual))["annual"]],
                         ["2021", "2022", "2023", "2024"])

    def test_week_based_year_crossing_new_year_keeps_fiscal_labels(self):
        annual = [fact("2020-12-28", "2022-01-02", 100, fy=2021, filed="2022-02-01"),
                  fact("2022-01-03", "2023-01-01", 100, fy=2022, filed="2023-02-01"),
                  fact("2023-01-02", "2023-12-31", 100, fy=2023, filed="2024-02-01")]
        self.assertEqual([p["fiscal_year"] for p in normalized(company(annual))["annual"]],
                         ["2021", "2022", "2023"])

    def test_q1_with_incorrect_fy_is_assigned_by_annual_dates(self):
        annual = [fact("2020-11-01", "2021-10-31", 100, filed="2021-12-01")]
        quarterly = [fact("2020-11-01", "2021-01-31", 25, fy=2020,
                          fp="Q1", form="10-Q", filed="2021-03-01")]
        q1 = normalized(company(annual, quarterly))["quarterly"][0]
        self.assertEqual((q1["fiscal_year"], q1["quarter"]), ("2021", "Q1"))

    def test_restated_quarter_in_annual_filing_is_not_dropped(self):
        annual = [fact("2024-01-01", "2024-12-31", 100)]
        quarterly = [fact("2024-04-01", "2024-06-30", 20, fp="Q2", form="10-Q", filed="2024-08-01"),
                     fact("2024-04-01", "2024-06-30", 30, fp="FY", filed="2025-03-01")]
        q2 = normalized(company(annual, quarterly))["quarterly"][0]
        self.assertEqual(q2["quarter"], "Q2")
        self.assertEqual(q2["metrics"]["net_income"], 30)
        self.assertEqual(q2["metric_sources"]["net_income"]["source_form"], "10-K")

    def test_ytd_cash_flows_become_discrete_quarters(self):
        annual = [fact("2025-01-01", "2025-12-31", 100)]
        quarters = [fact(start, end, 25, fp=f"Q{number}", form="10-Q")
                    for number, start, end in ((1, "2025-01-01", "2025-03-31"),
                                               (2, "2025-04-01", "2025-06-30"),
                                               (3, "2025-07-01", "2025-09-30"))]
        cash = [fact("2025-01-01", end, value, fp=f"Q{number}", form="10-Q")
                for number, end, value in ((1, "2025-03-31", 10), (2, "2025-06-30", 25), (3, "2025-09-30", 45))]
        periods = normalized(company(annual, quarters, cash))["quarterly"]
        self.assertEqual([p["metrics"]["operating_cash_flow"] for p in periods], [10, 15, 20])
        self.assertEqual(periods[-1]["metric_sources"]["operating_cash_flow"]["kind"], "derived_ytd_difference")

    def test_missing_q2_never_turns_nine_month_cash_flow_into_q3(self):
        annual = [fact("2025-01-01", "2025-12-31", 100)]
        quarters = [fact("2025-01-01", "2025-03-31", 25, fp="Q1", form="10-Q"),
                    fact("2025-07-01", "2025-09-30", 25, fp="Q3", form="10-Q")]
        cash = [fact("2025-01-01", "2025-03-31", 10, fp="Q1", form="10-Q"),
                fact("2025-01-01", "2025-09-30", 45, fp="Q3", form="10-Q")]
        q3 = normalized(company(annual, quarters, cash))["quarterly"][-1]
        self.assertNotIn("operating_cash_flow", q3["metrics"])

    def test_nonfinite_facts_are_not_financial_values(self):
        payload = company([fact("2025-01-01", "2025-12-31", 100)])
        payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0]["val"] = float("nan")
        self.assertNotIn("total_revenue", normalized(payload)["annual"][0]["metrics"])

    def test_total_revenue_is_not_replaced_by_a_contract_revenue_subset(self):
        annual = [fact("2025-01-01", "2025-12-31", 100)]
        payload = company(annual)
        payload["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"] = {
            "units": {"USD": [fact("2025-01-01", "2025-12-31", 30)]}}
        result = normalized(payload)["annual"][0]
        self.assertEqual(result["metrics"]["total_revenue"], 100)
        self.assertEqual(result["metric_sources"]["total_revenue"]["concept"], "us-gaap:Revenues")

    def test_income_available_to_common_is_not_mixed_with_total_net_income(self):
        annual = [fact("2025-01-01", "2025-12-31", 100)]
        quarters = [fact(start, end, 20, fp=f"Q{number}", form="10-Q") for number, start, end in
                    ((1, "2025-01-01", "2025-03-31"), (2, "2025-04-01", "2025-06-30"),
                     (3, "2025-07-01", "2025-09-30"))]
        payload = company(annual, quarters)
        payload["facts"]["us-gaap"]["NetIncomeLossAvailableToCommonStockholdersBasic"] = {
            "units": {"USD": [fact("2025-10-01", "2025-12-31", 30)]}}
        result = normalized(payload)
        grouped = _quarterly_by_year(result["quarterly"], result["annual"])
        self.assertEqual(grouped["2025"][-1]["metrics"]["net_income"], 40)

    def test_represented_year_end_one_day_apart_is_only_one_year(self):
        annual = [fact("2021-01-01", "2021-12-31", 100),
                  fact("2022-01-01", "2022-12-31", 100, filed="2023-03-01"),
                  fact("2022-01-03", "2023-01-01", 101, fy=2022, filed="2025-03-01"),
                  fact("2023-01-02", "2023-12-31", 110),
                  fact("2024-01-01", "2024-12-29", 120)]
        periods = normalized(company(annual))["annual"]
        self.assertEqual(len(periods), 4)
        year = next(p for p in periods if p["fiscal_year"] == "2022")
        self.assertEqual(year["period_end"], "2023-01-01")
        self.assertEqual(year["metrics"]["net_income"], 101)


class FinancialCompletenessTest(unittest.TestCase):
    def complete_payload(self):
        metrics = {metric: 100 for metric in ("total_revenue", "net_income", "total_assets",
                                               "total_liabilities", "stockholders_equity")}
        return {"annual": [{"fiscal_year": str(year), "period_end": f"{year}-12-31", "metrics": dict(metrics)}
                           for year in range(2021, 2026)],
                "quarterly_by_year": {str(year): [{"quarter": f"Q{quarter}", "metrics": dict(metrics)}
                                                  for quarter in range(1, 5)] for year in range(2021, 2026)}}

    def test_five_rows_with_duplicate_year_are_not_five_years(self):
        payload = self.complete_payload()
        payload["annual"][0]["fiscal_year"] = "2022"
        quality = assess_financial_payload(payload)
        self.assertFalse(quality["annual_complete"])
        self.assertFalse(quality["quarterly_complete"])
        self.assertTrue(quality["gaps"])

    def test_unprocessed_newer_transition_prevents_complete_badge(self):
        payload = self.complete_payload()
        payload["excluded_periods"] = [{"period_end": "2026-03-31", "source_form": "10-KT"},
                                       {"period_end": "2026-06-30", "source_form": "10-KT"}]
        quality = assess_financial_payload(payload)
        self.assertFalse(quality["annual_complete"])
        self.assertFalse(quality["quarterly_complete"])
        self.assertEqual(sum("10-KT" in gap for gap in quality["gaps"]), 1)

    def test_five_years_with_a_hole_are_not_consecutive(self):
        payload = self.complete_payload()
        payload["annual"][0].update(fiscal_year="2020", period_end="2020-12-31")
        self.assertFalse(assess_financial_payload(payload)["annual_complete"])

    def test_q4_with_only_balance_sheet_cannot_be_hidden_by_average(self):
        payload = self.complete_payload()
        q4 = payload["quarterly_by_year"]["2025"][-1]
        q4["metrics"].pop("total_revenue")
        q4["metrics"].pop("net_income")
        quality = assess_financial_payload(payload)
        self.assertFalse(quality["quarterly_complete"])
        self.assertEqual(quality["period_gaps"]["2025"]["missing_metrics"]["Q4"], ["total_revenue", "net_income"])

    def test_current_year_interim_is_retained_without_an_annual_report(self):
        annual = [{"period_end": "2025-12-31", "fiscal_year": "2025", "metrics": {"total_revenue": 100}}]
        quarters = [{"period_end": "2026-06-30", "fiscal_year": "2026", "quarter": "Q2", "metrics": {"total_revenue": 30}}]
        with patch("fastdeep_scanner.financials.load_universe_metadata", return_value={}):
            result = _build_financial_payload("TEST", annual_periods=annual, quarterly_periods=quarters,
                                              currency="USD", source="SEC EDGAR")
        self.assertIn("2026", result["quarterly_by_year"])
        self.assertEqual(result["data_quality"]["latest_quarter_period"], "2026-06-30")

    def test_reported_q4_eps_survives_filling_missing_balance_sheet(self):
        annual = [{"period_end": "2025-12-31", "metrics": {"total_assets": 100, "basic_eps": 4}, "ratios": {}}]
        q4 = {"period_end": "2025-12-31", "quarter": "Q4", "metrics": {"basic_eps": 1.25},
              "metric_sources": {"basic_eps": {"kind": "reported"}}}
        grouped = _quarterly_by_year([q4], annual)
        payload = _with_currency_presentation({"symbol": "TEST", "annual": annual, "quarterly_by_year": grouped})
        self.assertEqual(payload["quarterly_by_year"]["2025"][0]["metrics"]["basic_eps"], 1.25)
        self.assertEqual(payload["quarterly_by_year"]["2025"][0]["metrics"]["total_assets"], 100)

    def test_wrong_year_quarters_cannot_be_subtracted_to_make_q4(self):
        annual = [{"period_end": "2025-12-31", "fiscal_year": "2025", "metrics": {"total_revenue": 100, "total_assets": 200}}]
        quarters = [{"period_end": f"2024-{month}-30", "fiscal_year": "2025", "quarter": f"Q{quarter}",
                     "metrics": {"total_revenue": 20}} for quarter, month in ((1, "03"), (2, "06"), (3, "09"))]
        q4 = _quarterly_by_year(quarters, annual)["2025"][-1]
        self.assertNotIn("total_revenue", q4["metrics"])

    def test_reported_quarters_that_do_not_add_up_are_flagged_not_adjusted(self):
        payload = self.complete_payload()
        for number, month in ((1, "03"), (2, "06"), (3, "09"), (4, "12")):
            period = payload["quarterly_by_year"]["2025"][number - 1]
            period["period_end"] = f"2025-{month}-30"
            period["metrics"]["total_revenue"] = 20
            period["metrics"]["net_income"] = 25
        quality = assess_financial_payload(payload)
        self.assertFalse(quality["quarterly_complete"])
        self.assertEqual(quality["reconciliation_issues"][0]["difference"], -20)
        self.assertEqual(payload["quarterly_by_year"]["2025"][-1]["metrics"]["total_revenue"], 20)


if __name__ == "__main__":
    unittest.main()
