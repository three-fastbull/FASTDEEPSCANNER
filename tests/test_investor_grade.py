"""Guards for the checks that decide whether a result is safe to act on."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fastdeep_scanner import evidence
from fastdeep_scanner.currency import convert, price_scale, trading_currency
from fastdeep_scanner.liquidity import liquidity_profile, median_turnover
from fastdeep_scanner.models import FundamentalSnapshot, StockCandle
from fastdeep_scanner.patterns import detect_double_bottom
from fastdeep_scanner.research_journal import get_research, save_research
from fastdeep_scanner.timeframes import aggregate_candles
from fastdeep_scanner.trade_journal import close_trade, journal_summary, open_trade
from fastdeep_scanner.valuation import derive_valuation
from fastdeep_scanner.scanner import _decision


RATES = {"THB": 32.0, "HKD": 7.8, "CNY": 7.2}


def _candles(prices: list[float], start: date, symbol: str = "TEST", volume: float = 1000) -> list[StockCandle]:
    output = []
    current = start
    for price in prices:
        while current.weekday() >= 5:
            current += timedelta(days=1)
        output.append(
            StockCandle(current, symbol, price, price * 1.01, price * 0.99, price, volume)
        )
        current += timedelta(days=1)
    return output


class TimeframeTest(unittest.TestCase):
    def test_incomplete_period_is_dropped(self) -> None:
        candles = [
            StockCandle(date(2026, 8, 10), "TEST", 10, 12, 9, 11, 100),
            StockCandle(date(2026, 8, 14), "TEST", 11, 14, 10, 13, 200),
            StockCandle(date(2026, 8, 17), "TEST", 13, 15, 12, 14, 300),
            StockCandle(date(2026, 8, 19), "TEST", 14, 16, 13, 15, 400),
        ]
        weekly = aggregate_candles(candles, "W", as_of=date(2026, 8, 20))
        self.assertEqual(len(weekly), 1, "the week still trading must not be scored")
        self.assertEqual(weekly[0].date, date(2026, 8, 14))

    def test_completed_period_is_kept(self) -> None:
        candles = [
            StockCandle(date(2026, 8, 10), "TEST", 10, 12, 9, 11, 100),
            StockCandle(date(2026, 8, 14), "TEST", 11, 14, 10, 13, 200),
        ]
        weekly = aggregate_candles(candles, "W", as_of=date(2026, 8, 20))
        self.assertEqual(len(weekly), 1)
        self.assertEqual((weekly[0].high, weekly[0].low, weekly[0].volume), (14, 9, 300))


class LiquidityTest(unittest.TestCase):
    def test_turnover_is_converted_before_scoring(self) -> None:
        thai = _candles([100.0] * 60, date(2026, 5, 1), "AAA.BK", volume=1_000_000)
        us = _candles([100.0] * 60, date(2026, 5, 1), "AAA", volume=1_000_000)
        thai_profile = liquidity_profile(thai, "AAA.BK", "TH", rates=RATES)
        us_profile = liquidity_profile(us, "AAA", "US", rates=RATES)
        self.assertEqual(thai_profile["currency"], "THB")
        self.assertAlmostEqual(thai_profile["turnover_usd"], 100_000_000 / 32.0, places=2)
        self.assertGreater(us_profile["score"], thai_profile["score"])

    def test_thin_symbol_scores_low(self) -> None:
        thin = _candles([2.0] * 60, date(2026, 5, 1), "THIN", volume=500)
        self.assertLess(liquidity_profile(thin, "THIN", "US", rates=RATES)["score"], 40)

    def test_median_ignores_zero_volume_days(self) -> None:
        candles = _candles([10.0] * 30, date(2026, 5, 1), "AAA", volume=0)
        self.assertEqual(median_turnover(candles), 0.0)


class DoubleBottomTest(unittest.TestCase):
    """A W shape after a decline, with the neckline break still fresh."""

    BASE = (
        [100 - index * 0.47 for index in range(70)]
        + [67 + index * 0.5 for index in range(20)]
        + [77 - index * 0.5 for index in range(20)]
        + [68 + index * 0.45 for index in range(20)]
        + [78.5, 79.6, 80.4, 81.0]
    )

    def _candles_with_breakout_volume(self, prices: list[float], breakout_bars: int = 4):
        volumes = [1000.0] * (len(prices) - breakout_bars) + [2000.0] * breakout_bars
        candles = _candles(prices, date(2025, 1, 1))
        return [
            StockCandle(item.date, item.symbol, item.open, item.high, item.low, item.close, volume)
            for item, volume in zip(candles, volumes)
        ]

    def test_fresh_neckline_break_is_detected(self) -> None:
        hit = detect_double_bottom(self._candles_with_breakout_volume(list(self.BASE)))
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "double_bottom")

    def test_stale_break_is_rejected(self) -> None:
        """The same shape, but the neckline broke long ago and price drifted on."""
        drifted = list(self.BASE) + [81 + index * 0.05 for index in range(40)]
        self.assertIsNone(detect_double_bottom(self._candles_with_breakout_volume(drifted, 44)))


class ValuationTest(unittest.TestCase):
    def _snapshot(self, **overrides) -> FundamentalSnapshot:
        base = dict(
            symbol="TEST",
            name="Test",
            market="US",
            sector="Test",
            roe=15.0,
            roa=8.0,
            debt_to_equity=0.5,
            revenue_growth=10.0,
            profit_growth=12.0,
            gross_margin=40.0,
            net_margin=15.0,
            pe=0.0,
            pbv=0.0,
            dividend_yield=0.0,
            analyst_upside_pct=0.0,
            liquidity_score=80.0,
            moat="wide",
            ai_trend="leader",
            eps=5.0,
            book_value_per_share=25.0,
            reporting_currency="USD",
            trading_currency="USD",
            fundamentals_verified=True,
        )
        base.update(overrides)
        return FundamentalSnapshot(**base)

    def test_same_currency_multiples(self) -> None:
        result = derive_valuation(self._snapshot(), 100.0, RATES)
        self.assertTrue(result["verified"])
        self.assertEqual(result["pe"], 20.0)
        self.assertEqual(result["pbv"], 4.0)
        self.assertFalse(result["fx_adjusted"])

    def test_cross_currency_price_is_converted(self) -> None:
        snapshot = self._snapshot(
            symbol="0700.HK", trading_currency="HKD", reporting_currency="CNY"
        )
        result = derive_valuation(snapshot, 100.0, RATES)
        self.assertTrue(result["verified"])
        self.assertTrue(result["fx_adjusted"])
        expected_price = convert(100.0, "HKD", "CNY", RATES)
        self.assertAlmostEqual(result["pe"], round(expected_price / 5.0, 2), places=2)

    def test_missing_rate_blocks_publication(self) -> None:
        snapshot = self._snapshot(trading_currency="HKD", reporting_currency="XYZ")
        result = derive_valuation(snapshot, 100.0, RATES)
        self.assertFalse(result["verified"])
        self.assertIsNone(result["pe"])
        self.assertIn("ไม่มีอัตราแลกเปลี่ยน", result["note"])

    def test_unverified_financials_never_produce_a_multiple(self) -> None:
        result = derive_valuation(self._snapshot(fundamentals_verified=False), 100.0, RATES)
        self.assertFalse(result["verified"])
        self.assertIsNone(result["pe"])

    def test_london_pence_is_scaled_to_pounds(self) -> None:
        self.assertEqual(price_scale("BP.L"), 0.01)
        self.assertEqual(price_scale("AAPL"), 1.0)
        self.assertEqual(trading_currency("PTT.BK"), "THB")
        self.assertEqual(trading_currency("0700.HK"), "HKD")


class ResearchJournalTest(unittest.TestCase):
    def test_approval_requires_a_business_judgement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "journal.json"
            with self.assertRaises(ValueError):
                save_research("TEST", "Approved", "looks good", path)
            record = save_research(
                "TEST", "Research", "checked", path, moat="wide", ai_trend="leader", fair_value=120
            )
            self.assertTrue(record["research_verified"])
            self.assertFalse(record["company_profile_verified"])
            self.assertEqual(get_research("TEST", path)["fair_value"], 120.0)

    def test_company_profile_requires_evidence_and_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "journal.json"
            record = save_research(
                "TEST",
                "Research",
                path=path,
                moat="wide",
                ai_trend="leader",
                business_summary="บริษัทขายซอฟต์แวร์ให้ธุรกิจ",
                revenue_model="ค่าสมาชิกรายปี",
                revenue_segments="Subscription 90%\nServices 10%",
                key_customers="กระจายตัว ไม่มีลูกค้ารายเดียวเกิน 10%",
                competitors="PEER1, PEER2",
                moat_evidence="อัตราต่อสัญญาสูงและต้นทุนย้ายระบบสูง",
                risks="คู่แข่งลดราคา",
                invalidation="อัตราต่อสัญญาต่ำกว่า 80%",
                source_urls="https://example.com/annual-report",
                thesis="รายได้ประจำเติบโตและรักษาลูกค้าได้",
            )
            self.assertTrue(record["company_profile_verified"])

    def test_approved_status_requires_the_complete_company_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "journal.json"
            with self.assertRaises(ValueError):
                save_research(
                    "TEST",
                    "Approved",
                    path=path,
                    moat="wide",
                    ai_trend="leader",
                )

    def test_watch_status_stays_unverified(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "journal.json"
            record = save_research("TEST", "Watch", "just watching", path)
            self.assertFalse(record["research_verified"])


class EvidenceGateTest(unittest.TestCase):
    def test_partial_financial_history_cannot_be_a_candidate(self) -> None:
        decision = _decision(
            95.0,
            [],
            False,
            True,
            False,
            True,
            True,
            True,
        )
        self.assertEqual(decision, "งบยืนยันแล้ว แต่ประวัติยังไม่ครบ 5 ปี")

    def _write_study(self, directory: Path, return_edge: float, signals: int) -> None:
        payload = {
            "horizons": [20],
            "baseline": {"h20": {"average_return_pct_net": 1.0, "hit_rate_pct": 50.0}},
            "by_pattern": [
                {
                    "pattern": "retest",
                    "signals": signals,
                    "h20": {
                        "average_return_pct_net": 1.0 + return_edge,
                        "hit_rate_pct": 55.0,
                        "average_max_drawdown_pct": -5.0,
                    },
                    "edge_vs_baseline": {"h20": {"return_edge_pp": return_edge, "hit_rate_edge_pp": 5.0}},
                }
            ],
        }
        (directory / "fastdeep_event_study_D.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def _edge(self, return_edge: float, signals: int) -> dict:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            self._write_study(directory, return_edge, signals)
            original = evidence.STUDY_DIR
            evidence.STUDY_DIR = directory
            try:
                evidence._load_study.cache_clear()
                return evidence.pattern_edge("retest", "D")
            finally:
                evidence.STUDY_DIR = original
                evidence._load_study.cache_clear()

    def test_positive_edge_is_tradeable(self) -> None:
        result = self._edge(2.5, 900)
        self.assertEqual(result["verdict"], "edge")
        self.assertTrue(result["tradeable"])

    def test_negative_edge_is_not_tradeable(self) -> None:
        result = self._edge(-1.2, 900)
        self.assertEqual(result["verdict"], "no_edge")
        self.assertFalse(result["tradeable"])

    def test_small_sample_is_not_tradeable(self) -> None:
        result = self._edge(4.0, 12)
        self.assertEqual(result["verdict"], "insufficient")
        self.assertFalse(result["tradeable"])

    def test_missing_study_is_not_tradeable(self) -> None:
        original = evidence.STUDY_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            evidence.STUDY_DIR = Path(temp_dir)
            try:
                result = evidence.pattern_edge("retest", "D")
            finally:
                evidence.STUDY_DIR = original
        self.assertFalse(result["tradeable"])
        self.assertEqual(result["verdict"], "unmeasured")


class TradeJournalTest(unittest.TestCase):
    def test_round_trip_records_net_return_and_r_multiple(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "trades.json"
            trade = open_trade("TEST", entry=100.0, stop=90.0, targets=[120.0], path=path)
            self.assertEqual(trade["risk_pct"], 10.0)
            closed = close_trade(trade["id"], exit_price=110.0, cost_bps=30, path=path)
            self.assertAlmostEqual(closed["return_pct"], 10.0, places=3)
            self.assertAlmostEqual(closed["return_pct_net"], 9.7, places=3)
            self.assertAlmostEqual(closed["r_multiple"], 1.0, places=2)
            summary = journal_summary(path)
            self.assertEqual(summary["closed_count"], 1)
            self.assertEqual(summary["hit_rate_pct"], 100.0)

    def test_stop_above_entry_is_rejected_for_a_long(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "trades.json"
            with self.assertRaises(ValueError):
                open_trade("TEST", entry=100.0, stop=110.0, path=path)


if __name__ == "__main__":
    unittest.main()


class RiskPlanTest(unittest.TestCase):
    def test_stop_is_bounded_by_volatility_not_by_a_distant_swing_low(self) -> None:
        from fastdeep_scanner.patterns import atr_value
        from fastdeep_scanner.risk import MAXIMUM_ATR_MULTIPLE, build_risk_plan

        # A stock that ran up hard leaves its 35-bar low far below the entry.
        prices = [40.0] * 20 + [40 + index * 1.2 for index in range(40)]
        candles = _candles(prices, date(2025, 1, 1))
        plan = build_risk_plan(candles, [])
        widest = candles[-1].close - atr_value(candles) * MAXIMUM_ATR_MULTIPLE
        self.assertGreaterEqual(plan.stop, widest - 1e-6)
        self.assertLess(plan.stop, plan.entry)
        self.assertGreater(plan.risk_pct, 0)
