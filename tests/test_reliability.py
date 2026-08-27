from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from fastdeep_scanner.data_health import financial_data_health, price_data_health
from fastdeep_scanner.models import ScanCriteria, StockCandle
from fastdeep_scanner.backtest import run_event_study
from fastdeep_scanner.timeframes import aggregate_candles
from fastdeep_scanner.research_journal import get_research, save_research


class ReliabilityTest(unittest.TestCase):
    def test_financial_freshness_excludes_symbols_outside_the_coverage_universe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache = root / "cache"
            cache.mkdir()
            for symbol in ("AAPL", "DOHOME_BK", "OUTSIDE"):
                (cache / f"{symbol}.json").write_text("{}", encoding="utf-8")
            coverage = root / "coverage.json"
            coverage.write_text(json.dumps({
                "symbols_requested": 2, "cached_symbols": 2,
                "items": [{"symbol": "AAPL"}, {"symbol": "DOHOME.BK"}],
            }), encoding="utf-8")
            health = financial_data_health(
                cache, coverage_path=coverage, status_path=root / "status.json",
                sec_status_path=root / "sec.json",
            )
            self.assertEqual(health["fresh_symbols"], 2)
            self.assertEqual(health["cached_symbols"], 2)

    def test_weekly_aggregation_keeps_ohlcv_semantics(self) -> None:
        candles = [
            StockCandle(date(2026, 8, 3), "TEST", 10, 12, 9, 11, 100),
            StockCandle(date(2026, 8, 4), "TEST", 11, 14, 10, 13, 200),
            StockCandle(date(2026, 8, 10), "TEST", 13, 15, 12, 14, 300),
        ]
        weekly = aggregate_candles(candles, "W", as_of=date(2026, 8, 20))
        self.assertEqual(len(weekly), 2)
        self.assertEqual((weekly[0].open, weekly[0].high, weekly[0].low, weekly[0].close, weekly[0].volume), (10, 14, 9, 13, 300))

    def test_data_health_marks_stale_prices_non_publishable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            price_path = root / "prices.csv"
            price_path.write_text(
                "date,symbol,open,high,low,close,volume\n2026-07-13,TEST,1,1,1,1,1\n",
                encoding="utf-8",
            )
            price_path.with_name("prices_source.json").write_text(
                json.dumps({"source": "test", "latest_candle_date": "2026-07-13", "symbols_requested": 1, "symbols_succeeded": 1, "failed": []}),
                encoding="utf-8",
            )
            health = price_data_health(price_path, status_path=root / "status.json", today=date(2026, 8, 20))
            self.assertEqual(health["state"], "stale")
            self.assertFalse(health["can_publish"])

    def test_data_health_accepts_previous_business_day(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            price_path = root / "prices.csv"
            price_path.write_text(
                "date,symbol,open,high,low,close,volume\n2026-08-19,TEST,1,1,1,1,1\n",
                encoding="utf-8",
            )
            price_path.with_name("prices_source.json").write_text(
                json.dumps({"source": "test", "latest_candle_date": "2026-08-19", "symbols_requested": 1, "symbols_succeeded": 1, "failed": []}),
                encoding="utf-8",
            )
            health = price_data_health(price_path, status_path=root / "status.json", today=date(2026, 8, 20))
            self.assertEqual(health["state"], "ready")
            self.assertTrue(health["can_publish"])

    def test_event_study_reports_method_and_pattern_summary(self) -> None:
        import os

        os.environ["FASTDEEP_USE_SAMPLE_DATA"] = "1"
        try:
            study = run_event_study(
                ScanCriteria(patterns=("breakout",), min_score=45),
                horizons=(5, 10),
                cooldown_bars=20,
            )
        finally:
            os.environ.pop("FASTDEEP_USE_SAMPLE_DATA", None)
        self.assertIn("Does not model portfolio sizing", study["method"])
        self.assertIsInstance(study["by_pattern"], list)
        self.assertIn("baseline", study)
        self.assertIn("edge_vs_baseline", study)

    def test_research_journal_persists_a_symbol_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "journal.json"
            saved = save_research("test", "Research", "Verify cash flow", path)
            loaded = get_research("TEST", path)
            self.assertEqual(saved["status"], "Research")
            self.assertEqual(loaded["note"], "Verify cash flow")


if __name__ == "__main__":
    unittest.main()
