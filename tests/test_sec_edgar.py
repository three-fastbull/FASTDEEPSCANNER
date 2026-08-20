"""การเลือกนิติบุคคลที่ถูกต้องของแต่ละ ticker

``company_tickers.json`` ของ SEC ชี้ไปที่ผู้จดทะเบียนล่าสุด ซึ่งอาจเป็นบริษัท
โฮลดิ้งที่เพิ่งตั้ง เอนทิตีที่ปรับโครงสร้าง หรือบริษัทลูกที่เป็นห้างหุ้นส่วน
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from fastdeep_scanner.sec_edgar import _better_filing_history, _latest_period


def _history(years: list[int], name: str = "Entity") -> dict:
    return {
        "entity_name": name,
        "annual": [{"period_end": f"{year}-12-31", "metrics": {}} for year in years],
    }


class FilingHistorySelectionTest(unittest.TestCase):
    def _recent_year(self) -> int:
        return date.today().year - 1

    def test_current_entity_wins_over_a_longer_but_abandoned_one(self) -> None:
        """BLK: เอนทิตีเก่ามีประวัติยาวกว่า แต่หยุดยื่นไปแล้ว"""
        recent = self._recent_year()
        live = _history([recent - 1, recent], "BlackRock, Inc.")
        abandoned = _history([recent - 7, recent - 6, recent - 5, recent - 4, recent - 3], "BlackRock Finance")
        self.assertIs(_better_filing_history(live, abandoned), live)
        self.assertIs(_better_filing_history(abandoned, live), live)

    def test_longer_history_wins_when_both_are_current(self) -> None:
        """EQR: ทั้งคู่ยังยื่นอยู่ จึงเลือกชุดที่ย้อนหลังได้ยาวกว่า"""
        recent = self._recent_year()
        short = _history([recent], "Operating Partnership")
        deep = _history([recent - 4, recent - 3, recent - 2, recent - 1, recent], "Equity Residential")
        self.assertIs(_better_filing_history(short, deep), deep)
        self.assertIs(_better_filing_history(deep, short), deep)

    def test_a_missing_candidate_never_replaces_a_real_one(self) -> None:
        recent = self._recent_year()
        real = _history([recent - 1, recent])
        self.assertIs(_better_filing_history(real, None), real)
        self.assertIs(_better_filing_history(None, real), real)
        self.assertIsNone(_better_filing_history(None, None))

    def test_between_two_stale_entities_the_more_recent_one_wins(self) -> None:
        older = _history([2015, 2016, 2017])
        newer = _history([2018, 2019, 2020])
        self.assertIs(_better_filing_history(older, newer), newer)

    def test_latest_period_reads_the_newest_filing(self) -> None:
        self.assertEqual(_latest_period(_history([2021, 2025, 2023])), "2025-12-31")
        self.assertEqual(_latest_period({"annual": []}), "")
        self.assertEqual(_latest_period(None), "")

    def test_staleness_boundary_uses_eighteen_months(self) -> None:
        from fastdeep_scanner.sec_edgar import STALE_FILING_MONTHS

        self.assertEqual(STALE_FILING_MONTHS, 18)
        cutoff = date.today() - timedelta(days=STALE_FILING_MONTHS * 30)
        just_inside = {"annual": [{"period_end": (cutoff + timedelta(days=20)).isoformat()}]}
        long_gone = {"annual": [{"period_end": (cutoff - timedelta(days=400)).isoformat()}]}
        # ชุดที่ยังยื่นอยู่ชนะแม้จะมีเพียงงวดเดียว
        self.assertIs(_better_filing_history(long_gone, just_inside), just_inside)


if __name__ == "__main__":
    unittest.main()
