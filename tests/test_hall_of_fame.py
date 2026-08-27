from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date

from fastdeep_scanner.hall_of_fame import evaluate_symbol, xirr
from fastdeep_scanner.models import StockCandle


def _month_sequence(year: int, month: int, count: int):
    for offset in range(count):
        number = year * 12 + month - 1 + offset
        yield date(number // 12, number % 12 + 1, 1)


def _monthly_candles(annual_growth: float, months: int = 121) -> list[StockCandle]:
    factor = (1 + annual_growth) ** (1 / 12)
    price = 100.0
    rows: list[StockCandle] = []
    for when in _month_sequence(2016, 8, months):
        rows.append(
            StockCandle(
                date=when,
                symbol="TEST",
                open=price,
                high=price,
                low=price,
                close=price,
                volume=1_000_000,
                adjusted_close=price,
                adjusted_open=price,
            )
        )
        price *= factor
    return rows


class HallOfFameTest(unittest.TestCase):
    def test_xirr_matches_a_known_single_cash_flow_return(self) -> None:
        result = xirr([(date(2025, 1, 1), -100), (date(2026, 1, 1), 120)])
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result or 0, 0.2, places=3)

    def test_xirr_matches_the_published_excel_irregular_cashflow_example(self) -> None:
        result = xirr([
            (date(2008, 1, 1), -10_000),
            (date(2008, 3, 1), 2_750),
            (date(2008, 10, 30), 4_250),
            (date(2009, 2, 15), 3_250),
            (date(2009, 4, 1), 2_750),
        ])
        self.assertAlmostEqual(result, 0.373362535, places=7)

    def test_dca_uses_money_weighted_annualized_return(self) -> None:
        result = evaluate_symbol(_monthly_candles(0.20), as_of=date(2026, 8, 1))
        self.assertIsNotNone(result)
        self.assertEqual(result["months"], 121)
        self.assertEqual(result["total_invested"], 700_000)
        self.assertAlmostEqual(result["annualized_return_pct"], 20.0, delta=0.2)
        self.assertGreater(result["total_gain_pct"], 0)
        self.assertAlmostEqual(result["price_cagr_pct"], 20.0, delta=0.2)

    def test_short_history_is_not_ranked_as_a_ten_year_leader(self) -> None:
        result = evaluate_symbol(_monthly_candles(0.30, months=60), as_of=date(2021, 7, 1))
        self.assertIsNone(result)

    def test_missing_middle_month_does_not_silently_skip_a_contribution(self) -> None:
        candles = _monthly_candles(0.20)
        candles.pop(60)
        self.assertIsNone(evaluate_symbol(candles, as_of=date(2026, 8, 1)))

    def test_unadjusted_middle_month_is_not_ranked_as_adjusted_return(self) -> None:
        candles = _monthly_candles(0.20)
        candles[60] = replace(candles[60], adjusted_close=None, adjusted_open=None)
        self.assertIsNone(evaluate_symbol(candles, as_of=date(2026, 8, 1)))

    def test_duplicate_current_month_does_not_add_an_extra_dca(self) -> None:
        candles = _monthly_candles(0.20)
        baseline = evaluate_symbol(candles, as_of=date(2026, 8, 1))
        final_close = candles[-1].adjusted_close or candles[-1].close
        candles.append(
            StockCandle(
                date=date(2026, 8, 26),
                symbol="TEST",
                open=1.0,
                high=final_close,
                low=1.0,
                close=final_close,
                volume=1_000_000,
                adjusted_close=final_close,
                adjusted_open=1.0,
            )
        )
        result = evaluate_symbol(candles, as_of=date(2026, 8, 26))

        self.assertIsNotNone(baseline)
        self.assertIsNotNone(result)
        self.assertEqual(result["months"], 121)
        self.assertEqual(result["total_invested"], 700_000)
        self.assertEqual(result["ending_value"], baseline["ending_value"])
        self.assertEqual(result["end_date"], "2026-08-26")


if __name__ == "__main__":
    unittest.main()
