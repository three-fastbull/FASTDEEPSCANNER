"""รายได้แยกส่วนงานจากตารางในงบ โดยใช้การกระทบยอดเป็นตัวตัดสิน"""

from __future__ import annotations

import unittest

from fastdeep_scanner.filing_segments import (
    clean_segment_name,
    parse_table,
    reconciled_segments,
    segments_from_rows,
    unit_scale,
)


def _table(rows: list[str]) -> str:
    body = "".join(f"<tr>{''.join(f'<td>{cell}</td>' for cell in row)}</tr>" for row in rows)
    return f"<table>{body}</table>"


APPLE_LIKE = [
    ["Revenue - Disaggregated Net Sales (Details) - USD ($) $ in Millions", "12 Months Ended"],
    ["Sep. 27, 2025"],
    ["Net sales", "$ 400,000"],
    ["iPhone"],
    ["Net sales", "200,000"],
    ["Mac"],
    ["Net sales", "50,000"],
    ["Services"],
    ["Net sales", "150,000"],
]

MIXED_DIMENSIONS = [
    ["NET OPERATING REVENUES (Details) - USD ($) $ in Millions"],
    ["Dec. 31, 2025"],
    ["Net operating revenues", "$ 48,000"],
    ["Concentrate operations"],
    ["Net operating revenues", "28,000"],
    ["Finished product operations"],
    ["Net operating revenues", "20,000"],
    ["United States"],
    ["Net operating revenues", "19,000"],
    ["International"],
    ["Net operating revenues", "29,000"],
]


class TableParsingTest(unittest.TestCase):
    def test_labels_and_numbers_are_separated(self) -> None:
        rows = parse_table(_table(APPLE_LIKE))
        by_label = [row for row in rows if row["label"] == "iPhone"]
        self.assertTrue(by_label)
        self.assertEqual(by_label[0]["values"], [])

    def test_currency_and_scale_come_from_the_header(self) -> None:
        rows = parse_table(_table(APPLE_LIKE))
        scale, currency = unit_scale(rows)
        self.assertEqual(scale, 1_000_000)
        self.assertEqual(currency, "USD")

    def test_thousands_and_billions_are_recognised(self) -> None:
        thousands = parse_table(_table([["Something (Details) $ in Thousands"], ["Net sales", "1,000"]]))
        billions = parse_table(_table([["Something (Details) $ in Billions"], ["Net sales", "1"]]))
        self.assertEqual(unit_scale(thousands)[0], 1_000)
        self.assertEqual(unit_scale(billions)[0], 1_000_000_000)

    def test_negative_numbers_in_brackets_are_read_as_negative(self) -> None:
        rows = parse_table(_table([["Header $ in Millions"], ["Cost of sales", "(2,500)"]]))
        self.assertEqual(rows[1]["values"], [-2500.0])


class SegmentPairingTest(unittest.TestCase):
    def test_the_heading_row_names_the_numbers_that_follow(self) -> None:
        pairs = segments_from_rows(parse_table(_table(APPLE_LIKE)))
        names = dict(pairs)
        self.assertEqual(names["iPhone"], 200000.0)
        self.assertEqual(names["Mac"], 50000.0)
        self.assertEqual(names["Services"], 150000.0)


class ReconciliationTest(unittest.TestCase):
    def test_a_split_that_adds_up_is_accepted(self) -> None:
        result = reconciled_segments(segments_from_rows(parse_table(_table(APPLE_LIKE))))
        self.assertIsNotNone(result)
        self.assertEqual(result["total"], 400000.0)
        self.assertEqual(len(result["segments"]), 3)
        self.assertAlmostEqual(sum(s["amount"] for s in result["segments"]), result["total"])

    def test_two_dimensions_mixed_together_are_rejected(self) -> None:
        """แยกตามสินค้าและตามภูมิภาคพร้อมกันจะนับซ้ำ ผลรวมจึงเกินยอดจริง"""
        self.assertIsNone(reconciled_segments(segments_from_rows(parse_table(_table(MIXED_DIMENSIONS)))))

    def test_a_split_that_misses_the_total_is_rejected(self) -> None:
        pairs = [("Total", 100.0), ("A", 40.0), ("B", 30.0)]
        self.assertIsNone(reconciled_segments(pairs))

    def test_too_few_rows_are_rejected(self) -> None:
        self.assertIsNone(reconciled_segments([("Total", 100.0), ("A", 100.0)]))

    def test_a_repeated_segment_name_is_rejected(self) -> None:
        pairs = [("Total", 100.0), ("A", 50.0), ("A", 50.0)]
        self.assertIsNone(reconciled_segments(pairs))

    def test_rounding_within_tolerance_still_reconciles(self) -> None:
        result = reconciled_segments([("Total", 1000.0), ("A", 600.0), ("B", 399.0)])
        self.assertIsNotNone(result, "ปัดเศษเล็กน้อยในงบไม่ควรทำให้ตกทั้งชุด")


class SegmentNameTest(unittest.TestCase):
    def test_generic_dimension_labels_are_dropped(self) -> None:
        self.assertEqual(clean_segment_name("Operating Segments | United States"), "United States")
        self.assertEqual(clean_segment_name("United States | Reportable Segments"), "United States")

    def test_a_meaningful_pair_is_kept_with_a_separator(self) -> None:
        self.assertEqual(
            clean_segment_name("United States | Concentrate operations"),
            "United States · Concentrate operations",
        )

    def test_a_plain_name_is_untouched(self) -> None:
        self.assertEqual(clean_segment_name("iPhone"), "iPhone")

    def test_an_all_generic_name_keeps_something_rather_than_going_blank(self) -> None:
        self.assertEqual(clean_segment_name("Operating Segments"), "Operating Segments")


if __name__ == "__main__":
    unittest.main()
