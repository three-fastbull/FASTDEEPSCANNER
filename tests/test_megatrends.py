"""การจัดกลุ่มอุตสาหกรรมและเมกะเทรนด์สำหรับหน้าคัดหุ้นแบบ Top-Down"""

from __future__ import annotations

import unittest

from fastdeep_scanner.megatrends import (
    INDUSTRY_GROUPS,
    INDUSTRY_LABELS,
    MEGATRENDS,
    UNCLASSIFIED,
    build_catalog,
    classify_industry,
    megatrends_for,
)


class ClassificationTest(unittest.TestCase):
    def test_industries_land_in_the_expected_group(self) -> None:
        cases = {
            "Semiconductors & Related Devices": "semiconductor",
            "Services-Prepackaged Software": "software",
            "Electronic Computers": "hardware",
            "Pharmaceutical Preparations": "healthcare",
            "Crude Petroleum & Natural Gas": "energy",
            "Electric Services": "utilities",
            "National Commercial Banks": "financials",
            "Fire, Marine & Casualty Insurance": "insurance",
            "Real Estate Investment Trusts": "realestate",
            "Motor Vehicles & Passenger Car Bodies": "automotive",
            "Retail-Variety Stores": "consumer",
            "Railroads, Line-Haul Operating": "transport",
            "Television Broadcasting Stations": "media",
        }
        for industry, expected in cases.items():
            self.assertEqual(classify_industry(industry), expected, industry)

    def test_an_unknown_industry_is_marked_rather_than_forced(self) -> None:
        self.assertEqual(classify_industry("Interstellar Mining Cooperative"), UNCLASSIFIED)
        self.assertEqual(classify_industry(""), UNCLASSIFIED)

    def test_every_group_key_has_a_label(self) -> None:
        for key, label, needles in INDUSTRY_GROUPS:
            self.assertTrue(label.strip(), key)
            self.assertTrue(needles, key)
            self.assertEqual(INDUSTRY_LABELS[key], label)

    def test_megatrends_only_reference_real_industry_groups(self) -> None:
        known = set(INDUSTRY_LABELS)
        for trend in MEGATRENDS:
            self.assertTrue(set(trend["industries"]) <= known, trend["key"])
            self.assertTrue(trend["thesis"].strip())
            self.assertTrue(trend["watch"].strip(), "ทุกเทรนด์ต้องบอกข้อควรระวังด้วย")

    def test_a_company_can_belong_to_several_trends(self) -> None:
        trends = megatrends_for("software")
        self.assertIn("ai", trends)
        self.assertIn("cloud", trends)

    def test_an_unclassified_company_belongs_to_no_trend(self) -> None:
        self.assertEqual(megatrends_for(UNCLASSIFIED), [])


class CatalogTest(unittest.TestCase):
    COMPANIES = [
        {"industry_group": "semiconductor", "megatrends": ["ai"]},
        {"industry_group": "software", "megatrends": ["ai", "cloud"]},
        {"industry_group": "software", "megatrends": ["ai", "cloud"]},
        {"industry_group": UNCLASSIFIED, "megatrends": []},
    ]

    def test_counts_follow_the_companies_supplied(self) -> None:
        catalog = build_catalog(self.COMPANIES)
        self.assertEqual(catalog["total"], 4)
        by_key = {trend["key"]: trend["count"] for trend in catalog["megatrends"]}
        self.assertEqual(by_key["ai"], 3)
        self.assertEqual(by_key["cloud"], 2)
        self.assertEqual(by_key["healthcare"], 0)

    def test_empty_groups_are_left_out_but_unclassified_is_shown(self) -> None:
        catalog = build_catalog(self.COMPANIES)
        keys = [item["key"] for item in catalog["industries"]]
        self.assertIn("semiconductor", keys)
        self.assertIn(UNCLASSIFIED, keys, "ต้องเห็นว่ามีบริษัทที่ยังไม่ถูกจัดกลุ่ม")
        self.assertNotIn("healthcare", keys)

    def test_the_caveat_states_that_a_code_is_not_revenue_exposure(self) -> None:
        catalog = build_catalog(self.COMPANIES)
        self.assertIn("ไม่ได้บอกสัดส่วนรายได้", catalog["caveat"])

    def test_no_companies_yields_an_empty_but_valid_catalog(self) -> None:
        catalog = build_catalog([])
        self.assertEqual(catalog["total"], 0)
        self.assertEqual(catalog["industries"], [])
        self.assertTrue(all(trend["count"] == 0 for trend in catalog["megatrends"]))


if __name__ == "__main__":
    unittest.main()
