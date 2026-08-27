from __future__ import annotations

import unittest
from unittest.mock import patch

from fastdeep_scanner.yahoo_prices import fetch_symbol_prices


class AdjustedPricesTest(unittest.TestCase):
    def _payload(self, adjusted: list[float | None] | None = None) -> dict:
        indicators = {"quote": [{"open": [80], "high": [110], "low": [70], "close": [100], "volume": [1000]}]}
        if adjusted is not None:
            indicators["adjclose"] = [{"adjclose": adjusted}]
        return {"chart": {"result": [{"timestamp": [1735689600], "indicators": indicators}]}}

    def test_open_and_close_use_the_same_adjustment_factor(self) -> None:
        with patch("fastdeep_scanner.yahoo_prices._download_json", return_value=self._payload([50])):
            row = fetch_symbol_prices("TEST")[0]
        self.assertEqual(row["adjusted_close"], 50)
        self.assertEqual(row["adjusted_open"], 40)
        self.assertEqual(row["close"], 100)

    def test_missing_adjusted_prices_are_not_filled_with_raw_prices(self) -> None:
        for adjusted in (None, [None], [0]):
            with self.subTest(adjusted=adjusted):
                with patch("fastdeep_scanner.yahoo_prices._download_json", return_value=self._payload(adjusted)):
                    row = fetch_symbol_prices("TEST")[0]
                self.assertEqual(row["adjusted_close"], "")
                self.assertEqual(row["adjusted_open"], "")


if __name__ == "__main__":
    unittest.main()
