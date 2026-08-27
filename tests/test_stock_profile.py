"""หน้ารู้จักหุ้นต้องสรุปตามงบจริง และต้องไม่เดาแทนข้อมูลที่ไม่มี"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from fastdeep_scanner.models import FundamentalSnapshot, StockCandle
from fastdeep_scanner.stock_profile import build_stock_profile


RATES = {"THB": 32.0, "HKD": 7.8, "CNY": 7.2}


def _snapshot(symbol: str = "TEST", market: str = "US", sector: str = "Software") -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=symbol,
        name=f"{symbol} Company",
        market=market,
        sector=sector,
        roe=0.0,
        roa=0.0,
        debt_to_equity=0.0,
        revenue_growth=0.0,
        profit_growth=0.0,
        gross_margin=0.0,
        net_margin=0.0,
        pe=0.0,
        pbv=0.0,
        dividend_yield=0.0,
        analyst_upside_pct=0.0,
        liquidity_score=80.0,
        moat="",
        ai_trend="",
    )


def _candles(price: float, symbol: str = "TEST", days: int = 400) -> list[StockCandle]:
    start = date(2026, 8, 19) - timedelta(days=days)
    output = []
    for offset in range(days):
        current = start + timedelta(days=offset)
        output.append(StockCandle(current, symbol, price, price, price, price, 1_000_000))
    return output


def _year(
    year: int,
    *,
    revenue: float,
    net_income: float,
    eps: float,
    equity: float,
    operating_income: float | None = None,
    operating_cash_flow: float | None = None,
    total_debt: float = 0.0,
    gross_margin: float = 40.0,
) -> dict:
    revenue = float(revenue)
    operating_income = operating_income if operating_income is not None else net_income * 1.25
    return {
        "period_end": f"{year}-12-31",
        "metrics": {
            "total_revenue": revenue,
            "gross_profit": revenue * gross_margin / 100,
            "operating_income": operating_income,
            "pretax_income": operating_income,
            "tax_provision": operating_income * 0.2,
            "net_income": net_income,
            "basic_eps": eps,
            "stockholders_equity": equity,
            "total_debt": total_debt,
            "operating_cash_flow": operating_cash_flow if operating_cash_flow is not None else net_income * 1.3,
            "free_cash_flow": net_income,
        },
        "ratios": {
            "roe": net_income / equity * 100 if equity else None,
            "roa": net_income / (equity * 1.5) * 100 if equity else None,
            "net_margin": net_income / revenue * 100 if revenue else None,
            "gross_margin": gross_margin,
            "debt_to_equity": total_debt / equity if equity else None,
        },
    }


def _financials(years: list[dict], currency: str = "USD") -> dict:
    return {"currency": currency, "annual": years}


def _growing_company(currency: str = "USD") -> dict:
    """บริษัทที่ผ่านทั้งสี่ด่าน ใช้เป็นฐานแล้วค่อยดัดให้ตกด่านทีละอย่าง"""
    return _financials(
        [
            _year(2022, revenue=1000, net_income=100, eps=1.00, equity=400, gross_margin=40.0),
            _year(2023, revenue=1250, net_income=130, eps=1.30, equity=470, gross_margin=41.0),
            _year(2024, revenue=1560, net_income=170, eps=1.70, equity=560, gross_margin=42.0),
            _year(2025, revenue=1950, net_income=220, eps=2.20, equity=680, gross_margin=43.0),
        ],
        currency,
    )


class ProfileAvailabilityTest(unittest.TestCase):
    def test_without_statements_the_page_says_so_instead_of_guessing(self) -> None:
        profile = build_stock_profile("TEST", None, _candles(50.0), _snapshot(), {}, RATES)
        self.assertFalse(profile["available"])
        self.assertIn("ยังไม่มีงบการเงิน", profile["reason"])
        self.assertEqual(profile["stages"], [])

    def test_price_return_uses_adjusted_prices_and_reports_annualized_return(self) -> None:
        candles = [
            StockCandle(date(2023, 1, 1), "TEST", 100, 100, 100, 100, 1_000, adjusted_close=100),
            StockCandle(date(2024, 1, 1), "TEST", 120, 120, 120, 120, 1_000, adjusted_close=120),
            StockCandle(date(2025, 1, 1), "TEST", 144, 144, 144, 144, 1_000, adjusted_close=144),
        ]
        profile = build_stock_profile("TEST", None, candles, _snapshot(), {}, RATES)
        result = profile["historical_return"]
        self.assertTrue(result["available"])
        self.assertEqual(result["basis"], "adjusted_close")
        self.assertAlmostEqual(result["total_return_pct"], 44.0, places=1)
        self.assertAlmostEqual(result["annualized_return_pct"], 20.0, delta=0.1)

    def test_single_year_of_statements_is_not_enough(self) -> None:
        financials = _financials([_year(2025, revenue=100, net_income=10, eps=1.0, equity=50)])
        profile = build_stock_profile("TEST", financials, _candles(50.0), _snapshot(), {}, RATES)
        self.assertFalse(profile["available"])

    def test_return_does_not_mix_adjusted_and_raw_price_bases(self) -> None:
        candles = [
            StockCandle(date(2023, 1, 1), "TEST", 100, 100, 100, 100, 1_000, adjusted_close=50),
            StockCandle(date(2025, 1, 1), "TEST", 120, 120, 120, 120, 1_000),
        ]
        result = build_stock_profile("TEST", None, candles, _snapshot(), {}, RATES)["historical_return"]
        self.assertEqual(result["basis"], "close")
        self.assertAlmostEqual(result["total_return_pct"], 20.0)


class QualityFilterTest(unittest.TestCase):
    def test_four_stages_pass_for_a_consistently_growing_company(self) -> None:
        profile = build_stock_profile("TEST", _growing_company(), _candles(20.0), _snapshot(), {}, RATES)
        self.assertEqual(profile["passed_stages"], 4)
        self.assertEqual([stage["title"] for stage in profile["stages"]], ["GROWTH", "QUALITY", "EFFICIENCY", "MANAGEMENT"])

    def test_flat_revenue_fails_the_growth_stage(self) -> None:
        financials = _financials(
            [
                _year(2022, revenue=1000, net_income=100, eps=1.0, equity=400),
                _year(2023, revenue=990, net_income=101, eps=1.01, equity=420),
                _year(2024, revenue=1005, net_income=99, eps=0.99, equity=440),
                _year(2025, revenue=1000, net_income=102, eps=1.02, equity=460),
            ]
        )
        profile = build_stock_profile("TEST", financials, _candles(10.0), _snapshot(), {}, RATES)
        growth = profile["stages"][0]
        self.assertFalse(growth["passed"])
        self.assertEqual(profile["verdict"]["key"], "avoid")
        self.assertIn("GROWTH", profile["verdict"]["note"])

    def test_heavy_debt_fails_the_quality_stage(self) -> None:
        years = _growing_company()["annual"]
        for entry in years:
            equity = entry["metrics"]["stockholders_equity"]
            entry["metrics"]["total_debt"] = equity * 3
            entry["ratios"]["debt_to_equity"] = 3.0
        profile = build_stock_profile("TEST", _financials(years), _candles(20.0), _snapshot(), {}, RATES)
        quality = profile["stages"][1]
        self.assertFalse(quality["passed"])
        debt_criterion = next(item for item in quality["criteria"] if "Debt" in item["label"])
        self.assertEqual(debt_criterion["state"], "fail")

    def test_insider_ownership_is_reported_as_unknown_not_invented(self) -> None:
        profile = build_stock_profile("TEST", _growing_company(), _candles(20.0), _snapshot(), {}, RATES)
        management = profile["stages"][3]
        insider = next(item for item in management["criteria"] if "Insider" in item["label"])
        self.assertEqual(insider["state"], "unknown")
        self.assertIsNone(insider["passed"])
        self.assertTrue(management["needs_manual_check"])

    def test_share_count_growing_faster_than_tolerance_fails_dilution(self) -> None:
        # กำไรโตแต่จำนวนหุ้นโตเร็วกว่า ผู้ถือหุ้นเดิมจึงถูกเจือจาง
        financials = _financials(
            [
                _year(2022, revenue=1000, net_income=100, eps=1.00, equity=400),
                _year(2023, revenue=1250, net_income=130, eps=1.05, equity=470),
                _year(2024, revenue=1560, net_income=170, eps=1.10, equity=560),
                _year(2025, revenue=1950, net_income=220, eps=1.15, equity=680),
            ]
        )
        profile = build_stock_profile("TEST", financials, _candles(20.0), _snapshot(), {}, RATES)
        management = profile["stages"][3]
        dilution = next(item for item in management["criteria"] if "Dilution" in item["label"])
        self.assertEqual(dilution["state"], "fail")


class LynchTypeTest(unittest.TestCase):
    def test_rapid_growth_is_classified_fast_grower(self) -> None:
        profile = build_stock_profile("TEST", _growing_company(), _candles(20.0), _snapshot(), {}, RATES)
        self.assertEqual(profile["lynch_type"]["key"], "fast_grower")

    def test_return_from_a_loss_is_classified_turnaround(self) -> None:
        financials = _financials(
            [
                _year(2022, revenue=1000, net_income=-80, eps=-0.80, equity=300),
                _year(2023, revenue=1050, net_income=-20, eps=-0.20, equity=290),
                _year(2024, revenue=1200, net_income=40, eps=0.40, equity=330),
                _year(2025, revenue=1400, net_income=90, eps=0.90, equity=400),
            ]
        )
        profile = build_stock_profile("TEST", financials, _candles(12.0), _snapshot(), {}, RATES)
        self.assertEqual(profile["lynch_type"]["key"], "turnaround")

    def test_swinging_profits_are_classified_cyclical(self) -> None:
        financials = _financials(
            [
                _year(2022, revenue=1000, net_income=60, eps=0.60, equity=500),
                _year(2023, revenue=1400, net_income=210, eps=2.10, equity=650),
                _year(2024, revenue=900, net_income=40, eps=0.40, equity=600),
                _year(2025, revenue=1500, net_income=230, eps=2.30, equity=750),
            ]
        )
        profile = build_stock_profile("TEST", financials, _candles(18.0), _snapshot(), {}, RATES)
        self.assertEqual(profile["lynch_type"]["key"], "cyclical")


class ValuationTest(unittest.TestCase):
    def test_margin_of_safety_below_target_reads_as_wait(self) -> None:
        # ราคาสูงจนแทบไม่เหลือส่วนลด แม้ธุรกิจจะผ่านทุกด่าน
        research = {
            "moat": "wide",
            "ai_trend": "leader",
            "company_profile_verified": True,
            "business_summary": "ธุรกิจตัวอย่าง",
            "revenue_model": "ขายบริการแบบสมาชิก",
            "revenue_segments": "สมาชิก 100%",
            "key_customers": "ลูกค้ากระจายตัว",
            "competitors": "PEER",
            "moat_evidence": "ลูกค้าย้ายระบบได้ยาก",
            "risks": "การแข่งขัน",
            "invalidation": "ลูกค้าลดลงต่อเนื่อง",
            "source_urls": "https://example.com/annual-report",
            "thesis": "รายได้ประจำเติบโต",
        }
        profile = build_stock_profile("TEST", _growing_company(), _candles(60.0), _snapshot(), research, RATES)
        self.assertEqual(profile["passed_stages"], 4)
        self.assertEqual(profile["verdict"]["key"], "wait")
        self.assertLess(profile["valuation"]["margin_of_safety_pct"], 20)

    def test_peg_is_skipped_when_growth_is_too_slow_for_it(self) -> None:
        financials = _financials(
            [
                _year(2022, revenue=1000, net_income=100, eps=1.00, equity=400),
                _year(2023, revenue=1030, net_income=103, eps=1.03, equity=430),
                _year(2024, revenue=1060, net_income=106, eps=1.06, equity=460),
                _year(2025, revenue=1090, net_income=109, eps=1.09, equity=490),
            ]
        )
        profile = build_stock_profile("TEST", financials, _candles(15.0), _snapshot(), {}, RATES)
        peg = next(item for item in profile["valuation"]["methods"] if item["key"] == "peg")
        self.assertTrue(peg["skipped"])
        self.assertIsNone(peg["fair_value"])

    def test_price_is_converted_when_the_filing_currency_differs(self) -> None:
        profile = build_stock_profile(
            "0700.HK",
            _growing_company("CNY"),
            _candles(20.0, "0700.HK"),
            _snapshot("0700.HK", market="HK"),
            {},
            RATES,
        )
        self.assertTrue(profile["fx_adjusted"])
        self.assertEqual(profile["trading_currency"], "HKD")
        self.assertEqual(profile["reporting_currency"], "CNY")
        expected = 20.0 / RATES["HKD"] * RATES["CNY"]
        self.assertAlmostEqual(profile["price_in_reporting"], round(expected, 4), places=3)

    def test_historical_pe_uses_the_price_on_each_period_end(self) -> None:
        profile = build_stock_profile("TEST", _growing_company(), _candles(30.0), _snapshot(), {}, RATES)
        history = profile["pe_history"]
        self.assertTrue(history)
        for row in history:
            self.assertAlmostEqual(row["pe"], round(30.0 / row["eps"], 2), places=1)


class QualitativeTest(unittest.TestCase):
    def test_reference_facts_do_not_approve_the_investment(self) -> None:
        profile = build_stock_profile("TRV", _growing_company(), _candles(20.0, "TRV"), _snapshot("TRV"), {}, RATES)
        self.assertTrue(profile["business"]["reference"]["available"])
        self.assertFalse(profile["business"]["verified"])
        self.assertEqual(profile["verdict"]["key"], "research")
        self.assertFalse(profile["verdict"]["checklist"][1]["passed"])
        self.assertIn("มีข้อมูลอ้างอิงแล้ว", profile["verdict"]["checklist"][1]["detail"])
        self.assertNotIn("ยังไม่มีหลักฐาน", profile["verdict"]["note"])

    def test_quantitative_pass_is_not_a_buy_before_company_research(self) -> None:
        profile = build_stock_profile("TEST", _growing_company(), _candles(20.0), _snapshot(), {}, RATES)
        self.assertEqual(profile["passed_stages"], 4)
        self.assertEqual(profile["verdict"]["key"], "research")
        self.assertEqual(profile["verdict"]["total_checks"], 4)
        self.assertEqual(len(profile["verdict"]["checklist"]), 4)
        self.assertIn("งบการเงิน", profile["verdict"]["checklist"][0]["label"])

    def test_recorded_analyst_review_is_surfaced(self) -> None:
        review = {
            "moat": "wide",
            "ai_trend": "leader",
            "thesis": "แพลตฟอร์มที่ลูกค้าย้ายออกยาก",
            "status": "Approved",
            "research_verified": True,
        }
        profile = build_stock_profile("TEST", _growing_company(), _candles(20.0), _snapshot(), review, RATES)
        self.assertTrue(profile["qualitative"]["recorded"])
        self.assertEqual(profile["qualitative"]["moat"], "wide")

    def test_five_forces_and_flow_are_always_present_as_prompts(self) -> None:
        profile = build_stock_profile("TEST", None, _candles(20.0), _snapshot(), {}, RATES)
        self.assertEqual(len(profile["five_forces"]), 5)
        self.assertEqual(len(profile["flow"]), 8)


if __name__ == "__main__":
    unittest.main()


class TrendSummaryTest(unittest.TestCase):
    def _summary(self, financials: dict) -> dict:
        profile = build_stock_profile("TEST", financials, _candles(20.0), _snapshot(), {}, RATES)
        return {row["key"]: row for row in profile["series_summary"]}

    def test_money_rows_report_average_growth_per_year(self) -> None:
        rows = self._summary(_growing_company())
        revenue = rows["revenue"]["trend"]
        self.assertEqual(revenue["kind"], "cagr")
        self.assertGreater(revenue["value"], 20)
        self.assertIn("โตเฉลี่ย", revenue["label"])
        self.assertIn("ต่อปี", revenue["label"])
        self.assertEqual(revenue["tone"], "ok")

    def test_growth_snapshot_reports_compound_and_total_growth_separately(self) -> None:
        profile = build_stock_profile("TEST", _growing_company(), _candles(20.0), _snapshot(), {}, RATES)
        revenue = profile["growth_snapshot"]["revenue"]
        self.assertTrue(revenue["available"])
        self.assertGreater(revenue["cagr_pct"], 20)
        self.assertGreater(revenue["total_change_pct"], revenue["cagr_pct"])

    def test_missing_year_uses_calendar_span_and_breaks_growth_streak(self) -> None:
        financials = _growing_company()
        financials["annual"].pop(1)
        profile = build_stock_profile("TEST", financials, _candles(20.0), _snapshot(), {}, RATES)
        growth = profile["growth_snapshot"]["revenue"]
        self.assertEqual(growth["years"], 3)
        self.assertAlmostEqual(growth["cagr_pct"], (1.95 ** (1 / 3) - 1) * 100, places=2)
        self.assertFalse(profile["stages"][0]["passed"])

    def test_missing_metric_keeps_the_original_year_spacing(self) -> None:
        financials = _growing_company()
        financials["annual"][1]["metrics"]["total_revenue"] = None
        revenue = self._summary(financials)["revenue"]["trend"]
        self.assertEqual(revenue["years"], 3)
        self.assertAlmostEqual(revenue["value"], (1.95 ** (1 / 3) - 1) * 100, places=2)

    def test_duplicate_year_does_not_report_a_zero_year_cagr(self) -> None:
        from fastdeep_scanner.stock_profile import _growth_stat, _trend_cagr

        self.assertFalse(_growth_stat([100, 120], [2025, 2025])["available"])
        self.assertEqual(_trend_cagr([100, 120], period_years=[2025, 2025])["kind"], "none")

    def test_shrinking_revenue_is_reported_as_getting_worse(self) -> None:
        financials = _financials(
            [
                _year(2022, revenue=2000, net_income=200, eps=2.00, equity=800),
                _year(2023, revenue=1700, net_income=150, eps=1.50, equity=780),
                _year(2024, revenue=1500, net_income=120, eps=1.20, equity=760),
                _year(2025, revenue=1300, net_income=90, eps=0.90, equity=740),
            ]
        )
        revenue = self._summary(financials)["revenue"]["trend"]
        self.assertLess(revenue["value"], 0)
        self.assertIn("แย่ลงเฉลี่ย", revenue["label"])
        self.assertEqual(revenue["tone"], "bad")

    def test_ratio_rows_report_point_change_not_compound_growth(self) -> None:
        """ROE ที่ขยับ 10% เป็น 15% คือ +5 จุด ไม่ใช่โต 50%"""
        rows = self._summary(_growing_company())
        roe = rows["roe"]["trend"]
        self.assertEqual(roe["kind"], "change")
        self.assertIn("จุด", roe["label"])
        self.assertIn("ล่าสุด", roe["label"])

    def test_falling_debt_reads_as_an_improvement(self) -> None:
        years = _growing_company()["annual"]
        for entry, multiple in zip(years, (3.0, 2.2, 1.4, 0.6)):
            equity = entry["metrics"]["stockholders_equity"]
            entry["metrics"]["total_debt"] = equity * multiple
            entry["ratios"]["debt_to_equity"] = multiple
        debt = self._summary(_financials(years))["debt_to_equity"]["trend"]
        self.assertEqual(debt["tone"], "ok")
        self.assertIn("ลดลง", debt["label"])
        self.assertIn("ดีขึ้น", debt["label"])

    def test_swing_from_loss_to_profit_is_described_in_words(self) -> None:
        financials = _financials(
            [
                _year(2022, revenue=1000, net_income=-50, eps=-0.50, equity=300),
                _year(2023, revenue=1100, net_income=-10, eps=-0.10, equity=300),
                _year(2024, revenue=1200, net_income=30, eps=0.30, equity=330),
                _year(2025, revenue=1300, net_income=80, eps=0.80, equity=400),
            ]
        )
        profit = self._summary(financials)["net_income"]["trend"]
        self.assertEqual(profit["kind"], "turn")
        self.assertIn("พลิกจากติดลบเป็นบวก", profit["label"])


class NegativeEquityTest(unittest.TestCase):
    """ทุนติดลบเคยทำให้ ROE พุ่งเป็นหมื่นเปอร์เซ็นต์แล้วผ่านด่านคุณภาพ"""

    def _statements(self) -> dict:
        from fastdeep_scanner.financials import _add_ratios

        periods = [
            {
                "period_end": f"{year}-12-31",
                "metrics": {
                    "total_revenue": 60000.0,
                    "gross_profit": 42000.0,
                    "operating_income": 12000.0,
                    "pretax_income": 10000.0,
                    "tax_provision": 2000.0,
                    "net_income": 4226.0,
                    "basic_eps": 2.40,
                    "total_assets": 134000.0,
                    "stockholders_equity": equity,
                    "total_debt": 60000.0,
                    "operating_cash_flow": 18000.0,
                    "free_cash_flow": 16000.0,
                },
            }
            for year, equity in ((2022, 17254.0), (2023, 10360.0), (2024, 3325.0), (2025, -3270.0))
        ]
        return {"currency": "USD", "annual": _add_ratios(periods)}

    def test_ratios_are_withheld_when_equity_is_negative(self) -> None:
        annual = self._statements()["annual"]
        latest = annual[-1]
        self.assertTrue(latest["negative_equity"])
        self.assertIsNone(latest["ratios"]["roe"])
        self.assertIsNone(latest["ratios"]["debt_to_equity"])
        self.assertIn("ติดลบ", latest["ratio_notes"]["roe"])
        # อัตราส่วนที่ไม่ได้อิงส่วนของผู้ถือหุ้นยังใช้ได้ตามปกติ
        self.assertIsNotNone(latest["ratios"]["net_margin"])
        self.assertIsNotNone(latest["ratios"]["roa"])

    def test_negative_equity_fails_the_quality_stage(self) -> None:
        profile = build_stock_profile("TEST", self._statements(), _candles(180.0), _snapshot(), {}, RATES)
        quality = profile["stages"][1]
        self.assertFalse(quality["passed"])
        self.assertTrue(quality["negative_equity"])
        roe = next(item for item in quality["criteria"] if "ROE" in item["label"])
        debt = next(item for item in quality["criteria"] if "Debt" in item["label"])
        self.assertEqual(roe["state"], "fail")
        self.assertEqual(debt["state"], "fail")
        self.assertIn("ติดลบ", roe["note"])
        self.assertEqual(profile["verdict"]["key"], "avoid")

    def test_a_thin_but_positive_equity_base_is_also_refused(self) -> None:
        from fastdeep_scanner.financials import _add_ratios

        # ทุนเหลือไม่ถึง 1% ของสินทรัพย์ ตัวหารเล็กจนอัตราส่วนไร้ความหมาย
        periods = [
            {
                "period_end": f"{year}-12-31",
                "metrics": {
                    "total_revenue": 50000.0,
                    "net_income": 3000.0,
                    "total_assets": 100000.0,
                    "stockholders_equity": 500.0,
                    "total_debt": 40000.0,
                },
            }
            for year in (2024, 2025)
        ]
        latest = _add_ratios(periods)[-1]
        self.assertIsNone(latest["ratios"]["roe"])
        self.assertIsNone(latest["ratios"]["debt_to_equity"])
        self.assertFalse(latest["negative_equity"])
