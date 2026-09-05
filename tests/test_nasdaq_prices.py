from __future__ import annotations

import io
import json
import unittest
from datetime import date
from unittest.mock import patch

from fastdeep_scanner.yahoo_prices import fetch_nasdaq_eod_price


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class NasdaqPriceTests(unittest.TestCase):
    def test_latest_eod_row_is_parsed_for_scanner_csv(self):
        payload = {
            "data": {
                "tradesTable": {
                    "rows": [
                        {
                            "date": "08/28/2026",
                            "close": "$319.70",
                            "volume": "38,649,400",
                            "open": "$316.845",
                            "high": "$322.37",
                            "low": "$315.4504",
                        },
                        {
                            "date": "08/27/2026",
                            "close": "$314.58",
                            "volume": "32,419,230",
                            "open": "$310.545",
                            "high": "$315.40",
                            "low": "$309.4001",
                        },
                    ]
                }
            },
            "status": {"rCode": 200},
        }
        response = _Response(json.dumps(payload).encode("utf-8"))
        with patch("fastdeep_scanner.yahoo_prices.urllib.request.urlopen", return_value=response):
            row = fetch_nasdaq_eod_price("AAPL", date(2026, 8, 20), date(2026, 8, 28))
        self.assertEqual(row["date"], "2026-08-28")
        self.assertEqual(row["symbol"], "AAPL")
        self.assertEqual(row["close"], 319.7)
        self.assertEqual(row["volume"], 38_649_400)
        self.assertEqual(row["adjusted_close"], 319.7)


if __name__ == "__main__":
    unittest.main()
