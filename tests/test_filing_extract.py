"""การสกัดข้อความจากแบบที่ยื่น และลำดับชั้นความน่าเชื่อถือของแต่ละช่อง"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastdeep_scanner.company_research import build_company_business
from fastdeep_scanner.filing_extract import (
    business_summary,
    customer_concentration,
    item1_body,
    load_filing_profiles,
    plain_text,
    save_filing_profiles,
    section_excerpt,
)


LONG_BUSINESS = (
    "The Company designs and sells industrial pumps used by water utilities and "
    "chemical plants across North America and Europe, and services the installed "
    "base through long term maintenance agreements that renew annually."
)
LONG_COMPETITION = (
    "The markets we serve are fragmented and highly competitive. We compete on "
    "delivery time, service coverage and total cost of ownership rather than on "
    "list price alone, and several competitors are larger than we are."
)


def _filing_html() -> str:
    """เอกสารจำลองที่มีสารบัญนำหน้าเนื้อหาจริง เหมือน 10-K ของจริง"""
    return f"""
    <html><body>
    <div>Table of Contents</div>
    <div>Item 1. Business 3</div>
    <div>Item 1A. Risk Factors 12</div>
    <div>Item 2. Properties 30</div>
    <div>Part I</div>
    <div>Item 1. Business</div>
    <div>{LONG_BUSINESS}</div>
    <div>Competition</div>
    <div>{LONG_COMPETITION}</div>
    <div>Human Capital</div>
    <div>We employed 4,200 people at year end across twelve manufacturing sites.</div>
    <div>Item 1A. Risk Factors</div>
    <div>Our results depend on capital spending by municipal water utilities.</div>
    </body></html>
    """


class TextExtractionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.text = plain_text(_filing_html())

    def test_the_table_of_contents_is_not_mistaken_for_the_business_section(self) -> None:
        body = item1_body(self.text)
        self.assertIn(LONG_BUSINESS, body)
        self.assertNotIn("Item 2. Properties 30", body)
        self.assertNotIn("Risk Factors", body)

    def test_summary_skips_headings_and_short_lines(self) -> None:
        summary = business_summary(item1_body(self.text))
        self.assertTrue(summary.startswith("The Company designs"))
        self.assertNotIn("Part I", summary)
        self.assertNotIn("Competition", summary)

    def test_competition_section_is_captured_with_its_heading(self) -> None:
        excerpt = section_excerpt(item1_body(self.text), r"competiti(?:on|ve[^\n]{0,40})")
        self.assertTrue(excerpt.startswith("Competition —"))
        self.assertIn("fragmented and highly competitive", excerpt)
        self.assertNotIn("Human Capital", excerpt)

    def test_missing_section_returns_empty_rather_than_a_guess(self) -> None:
        body = plain_text("<div>Item 1. Business</div><div>" + LONG_BUSINESS + "</div><div>Item 1A. Risk</div>")
        self.assertEqual(section_excerpt(item1_body(body), r"competiti(?:on|ve[^\n]{0,40})"), "")

    def test_customer_sentences_are_kept_whole(self) -> None:
        text = plain_text(
            "<p>No single customer accounted for more than 10% of net revenue in 2025.</p>"
        )
        found = customer_concentration(text)
        self.assertEqual(found, "No single customer accounted for more than 10% of net revenue in 2025.")

    def test_no_customer_disclosure_yields_nothing(self) -> None:
        self.assertEqual(customer_concentration(plain_text("<p>We sell to many buyers.</p>")), "")


class FilingStoreTest(unittest.TestCase):
    def test_a_store_written_then_read_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "filings.json"
            save_filing_profiles({"AAA": {"symbol": "AAA", "business_summary": "text"}}, path)
            self.assertEqual(load_filing_profiles(path)["AAA"]["business_summary"], "text")

    def test_an_unknown_schema_version_is_ignored_rather_than_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "filings.json"
            path.write_text(json.dumps({"schema_version": 99, "profiles": {"AAA": {}}}), encoding="utf-8")
            self.assertEqual(load_filing_profiles(path), {})

    def test_a_missing_store_is_not_an_error(self) -> None:
        self.assertEqual(load_filing_profiles(Path("does-not-exist.json")), {})


class TierPriorityTest(unittest.TestCase):
    """บันทึกของนักลงทุน > แคตตาล็อกที่ทบทวนแล้ว > ข้อความจากแบบที่ยื่น"""

    FILING = {
        "TEST": {
            "symbol": "TEST",
            "entity_name": "Test Corp",
            "industry": "Pumps",
            "form": "10-K",
            "filed_at": "2026-02-01",
            "period": "2025-12-31",
            "source_url": "https://www.sec.gov/Archives/edgar/data/1/x.htm",
            "business_summary": "Filing description of the business.",
            "competition": "Competition — the market is fragmented.",
            "customer_concentration": "No single customer exceeded 10% of revenue.",
            "found": {"business_summary": True, "competition": True, "customer_concentration": True},
        }
    }

    def _business(self, research: dict | None = None) -> dict:
        with patch("fastdeep_scanner.company_research.load_filing_profiles", return_value=self.FILING):
            return build_company_business("TEST", research or {}, path=Path("missing-catalog.json"))

    def test_filing_text_fills_a_blank_field(self) -> None:
        business = self._business()
        self.assertEqual(business["summary"], "Filing description of the business.")
        self.assertEqual(business["field_origins"]["summary"], "filing")
        self.assertEqual(business["field_origins"]["competitors"], "filing")
        self.assertTrue(business["filing"]["available"])

    def test_a_personal_note_outranks_the_filing_text(self) -> None:
        business = self._business({"business_summary": "สรุปด้วยคำของผมเอง"})
        self.assertEqual(business["summary"], "สรุปด้วยคำของผมเอง")
        self.assertEqual(business["field_origins"]["summary"], "journal")

    def test_the_filing_never_supplies_judgement_fields(self) -> None:
        business = self._business()
        for field in ("moat_evidence", "revenue_model", "revenue_segments", "risks", "invalidation"):
            self.assertEqual(business["field_origins"][field], "missing", field)
            self.assertEqual(business[field], "", field)

    def test_filing_text_alone_does_not_count_as_a_reviewed_company(self) -> None:
        business = self._business()
        self.assertFalse(business["verified"])
        self.assertFalse(business["reference"]["available"])

    def test_a_non_http_source_url_is_dropped(self) -> None:
        filing = {"TEST": {**self.FILING["TEST"], "source_url": "javascript:alert(1)"}}
        with patch("fastdeep_scanner.company_research.load_filing_profiles", return_value=filing):
            business = build_company_business("TEST", {}, path=Path("missing-catalog.json"))
        self.assertEqual(business["filing"]["source_url"], "")


if __name__ == "__main__":
    unittest.main()
