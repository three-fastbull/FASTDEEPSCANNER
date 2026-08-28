"""การย่อและแปลข้อความจากแบบที่ยื่นให้เป็นภาษาไทย"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from fastdeep_scanner.company_research import build_company_business
from fastdeep_scanner.summarize import (
    SYSTEM_PROMPT,
    SummaryError,
    _parse_reply,
    _source_text,
    summarize_profile,
)


PROFILE = {
    "symbol": "TEST",
    "entity_name": "Test Pumps Corporation",
    "industry": "Pumps & Pumping Equipment",
    "form": "10-K",
    "period": "2025-12-31",
    "source_url": "https://www.sec.gov/Archives/edgar/data/1/x.htm",
    "business_summary": "The company designs and sells industrial pumps to water utilities.",
    "competition": "Competition — the market is fragmented and price driven.",
    "customer_concentration": "No single customer accounted for more than 10% of revenue.",
}


def _reply(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


class PromptTest(unittest.TestCase):
    def test_the_prompt_forbids_adding_outside_knowledge(self) -> None:
        self.assertIn("ห้ามเติมความรู้ภายนอก", SYSTEM_PROMPT)
        self.assertIn("ห้ามแต่งขึ้น", SYSTEM_PROMPT)
        self.assertIn("ห้ามประเมินว่าหุ้นน่าซื้อหรือไม่", SYSTEM_PROMPT)

    def test_the_source_text_carries_only_the_stored_filing_sections(self) -> None:
        text = _source_text(PROFILE)
        self.assertIn("Test Pumps Corporation", text)
        self.assertIn("industrial pumps", text)
        self.assertIn("No single customer", text)

    def test_missing_sections_are_marked_rather_than_omitted(self) -> None:
        text = _source_text({**PROFILE, "competition": "", "customer_concentration": ""})
        self.assertEqual(text.count("(ไม่มี)"), 2)


class ReplyParsingTest(unittest.TestCase):
    def test_plain_json_is_read(self) -> None:
        parsed = _parse_reply('{"summary_th": "ขายปั๊มน้ำ", "revenue_model_th": "", "customers_th": "", "competition_th": ""}')
        self.assertEqual(parsed["summary_th"], "ขายปั๊มน้ำ")
        self.assertEqual(parsed["revenue_model_th"], "")

    def test_a_fenced_reply_is_still_read(self) -> None:
        parsed = _parse_reply('```json\n{"summary_th": "ขายปั๊มน้ำ"}\n```')
        self.assertEqual(parsed["summary_th"], "ขายปั๊มน้ำ")

    def test_missing_keys_become_blank_not_absent(self) -> None:
        parsed = _parse_reply('{"summary_th": "ก"}')
        self.assertEqual(set(parsed), {"summary_th", "revenue_model_th", "customers_th", "competition_th"})
        self.assertEqual(parsed["customers_th"], "")

    def test_a_non_json_reply_is_rejected(self) -> None:
        with self.assertRaises(SummaryError):
            _parse_reply("ขอโทษครับ ผมสรุปไม่ได้")


class SummarizeProfileTest(unittest.TestCase):
    def test_a_successful_call_keeps_the_link_to_the_filing(self) -> None:
        payload = _reply('{"summary_th": "ออกแบบและขายปั๊มอุตสาหกรรมให้การประปา", "revenue_model_th": "ขายเครื่องและบริการ", "customers_th": "ไม่มีลูกค้ารายใดเกิน 10%", "competition_th": "ตลาดกระจายตัว"}')
        with patch("fastdeep_scanner.summarize._request", return_value=payload):
            result = summarize_profile(PROFILE, key="test-key")
        self.assertEqual(result["summary_th"], "ออกแบบและขายปั๊มอุตสาหกรรมให้การประปา")
        self.assertEqual(result["source_url"], PROFILE["source_url"])
        self.assertEqual(result["period"], "2025-12-31")
        self.assertTrue(result["summarized_at"])

    def test_a_profile_without_filing_text_is_refused(self) -> None:
        with self.assertRaises(SummaryError):
            summarize_profile({**PROFILE, "business_summary": ""}, key="test-key")


class ThaiDisplayTest(unittest.TestCase):
    """คำแปลไทยต้องแทนที่ข้อความอังกฤษ แต่ยังนับเป็นชั้นเดียวกัน"""

    def _business(self, filing: dict) -> dict:
        with patch("fastdeep_scanner.company_research.load_filing_profiles", return_value={"TEST": filing}):
            return build_company_business("TEST", {}, path=Path("missing-catalog.json"))

    def test_thai_text_is_shown_instead_of_the_english_excerpt(self) -> None:
        business = self._business({**PROFILE, "thai": {"summary_th": "ออกแบบและขายปั๊มอุตสาหกรรม", "model": "claude-haiku-4-5-20251001"}})
        self.assertEqual(business["summary"], "ออกแบบและขายปั๊มอุตสาหกรรม")
        self.assertEqual(business["field_origins"]["summary"], "filing")
        self.assertTrue(business["filing"]["translated"])
        self.assertEqual(business["filing"]["language"], "th")

    def test_without_a_translation_the_english_excerpt_still_shows(self) -> None:
        business = self._business(PROFILE)
        self.assertIn("industrial pumps", business["summary"])
        self.assertFalse(business["filing"]["translated"])
        self.assertEqual(business["filing"]["language"], "en")

    def test_a_translation_still_does_not_supply_moat_or_segments(self) -> None:
        business = self._business({**PROFILE, "thai": {"summary_th": "ขายปั๊ม", "revenue_model_th": "ขายเครื่อง"}})
        self.assertEqual(business["revenue_model"], "ขายเครื่อง")
        self.assertEqual(business["field_origins"]["moat_evidence"], "missing")
        self.assertEqual(business["field_origins"]["revenue_segments"], "missing")


if __name__ == "__main__":
    unittest.main()
