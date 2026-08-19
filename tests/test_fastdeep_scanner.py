from __future__ import annotations

import os
import unittest

from fastdeep_scanner import ScanCriteria, scan_market
from fastdeep_scanner.data_io import load_market_data
from fastdeep_scanner.patterns import detect_patterns
from fastdeep_scanner.report import build_report_html


class FastDeepScannerTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["FASTDEEP_USE_SAMPLE_DATA"] = "1"

    def tearDown(self) -> None:
        os.environ.pop("FASTDEEP_USE_SAMPLE_DATA", None)

    def test_scan_returns_ranked_candidates(self) -> None:
        results = scan_market(ScanCriteria(min_score=55))
        self.assertGreaterEqual(len(results), 4)
        self.assertGreaterEqual(results[0].final_score, results[-1].final_score)
        self.assertTrue(any(result.symbol == "ADVANC.BK" for result in results))

    def test_cup_handle_sample_is_detected(self) -> None:
        candles_by_symbol, _ = load_market_data()
        hits = detect_patterns(candles_by_symbol["AOT.BK"], ("cup_handle",))
        self.assertEqual(hits[0].name, "cup_handle")

    def test_bearish_risk_targets_are_not_negative(self) -> None:
        results = scan_market(ScanCriteria(patterns=("head_shoulders",), min_score=45))
        ptt = next(result for result in results if result.symbol == "PTT.BK")
        self.assertEqual(ptt.risk_plan.bias, "Risk-off / avoid long")
        self.assertTrue(all(target > 0 for target in ptt.risk_plan.targets))

    def test_report_html_contains_symbol_and_verdict(self) -> None:
        candles_by_symbol, fundamentals = load_market_data()
        result = scan_market(ScanCriteria(min_score=55))[0]
        html = build_report_html(result, candles_by_symbol[result.symbol], fundamentals[result.symbol])
        self.assertIn(result.symbol, html)
        self.assertIn("Scanner Verdict", html)


if __name__ == "__main__":
    unittest.main()
