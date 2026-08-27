from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from fastdeep_scanner.company_research import CATALOG_PATH, build_company_business, load_company_catalog
from fastdeep_scanner.research_journal import get_research, save_research
from fastdeep_scanner.stock_profile import build_stock_profile


class CompanyResearchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    def test_published_catalog_has_sourced_businesses_and_comparisons(self) -> None:
        catalog = load_company_catalog()
        self.assertEqual(catalog["errors"], {})
        self.assertTrue({"TRV", "FIX", "AAPL", "NVDA", "0700.HK", "DOHOME.BK"} <= catalog["profiles"].keys())
        for symbol in catalog["profiles"]:
            with self.subTest(symbol=symbol):
                business = build_company_business(symbol)
                self.assertTrue(business["has_details"])
                self.assertFalse(business["verified"])
                for key in ("summary", "revenue_model", "revenue_segments", "key_customers", "competitors", "moat_evidence"):
                    self.assertTrue(business[key])
                    self.assertEqual(business["field_origins"][key], "reference")
                self.assertGreaterEqual(len(business["reference"]["peers"]), 2)

    def test_travelers_premium_shares_are_not_presented_as_total_revenue(self) -> None:
        breakdown = build_company_business("TRV")["reference"]["revenue_breakdown"]
        self.assertEqual(breakdown["total"], 44387)
        self.assertIn("เบี้ย", breakdown["basis"])
        self.assertIn("ไม่ใช่รายได้รวม", breakdown["note"])
        self.assertEqual([row["share_pct"] for row in breakdown["segments"]], [51.09, 9.6, 39.3])

    def test_alias_is_explicit_and_unknown_symbols_do_not_inherit_another_company(self) -> None:
        alias = build_company_business("tcehy")
        self.assertEqual(alias["reference"]["symbol"], "0700.HK")
        unknown = build_company_business("NOT_IN_CATALOG")
        self.assertFalse(unknown["has_details"])
        self.assertEqual(unknown["summary"], "")
        self.assertEqual(unknown["reference"]["status"], "missing")

    def test_missing_revenue_mix_never_manufactures_percentages(self) -> None:
        breakdown = build_company_business("DOHOME.BK")["reference"]["revenue_breakdown"]
        self.assertIsNone(breakdown["total"])
        self.assertTrue(all(segment["share_pct"] is None for segment in breakdown["segments"]))

    def test_personal_notes_override_only_their_own_field(self) -> None:
        journal = {"business_summary": "My own research", "moat": "niche", "status": "Research"}
        before = deepcopy(journal)
        result = build_company_business("TRV", journal)
        self.assertEqual(result["summary"], "My own research")
        self.assertEqual(result["field_origins"]["summary"], "journal")
        self.assertEqual(result["field_origins"]["competitors"], "reference")
        self.assertFalse(result["verified"])
        self.assertEqual(journal, before)

    def test_opening_profile_never_changes_or_approves_the_private_journal(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            save_research("TRV", "Research", note="Private note", path=path, moat="medium", ai_trend="neutral")
            original = path.read_bytes()
            journal = get_research("TRV", path)
            profile = build_stock_profile("TRV", None, [], SimpleNamespace(market="US", name="Travelers", sector="Financials"), journal)
            self.assertTrue(profile["business"]["has_details"])
            self.assertFalse(profile["business"]["verified"])
            self.assertFalse(profile["qualitative"]["company_profile_verified"])
            self.assertEqual(profile["research"]["business_summary"], "")
            self.assertEqual(profile["qualitative"]["status"], "Research")
            self.assertEqual(path.read_bytes(), original)
            with self.assertRaises(ValueError):
                save_research("TRV", "Approved", path=path)

    def test_cached_entries_are_not_mutated_between_requests(self) -> None:
        first = build_company_business("TRV")
        first["reference"]["peers"].clear()
        first["reference"]["revenue_breakdown"]["segments"][0]["amount"] = 0
        second = build_company_business("TRV")
        self.assertTrue(second["reference"]["peers"])
        self.assertEqual(second["reference"]["revenue_breakdown"]["segments"][0]["amount"], 22679)

    def test_old_reference_material_remains_available_but_is_marked_for_review(self) -> None:
        result = build_company_business("TRV", today=date(2027, 8, 27))["reference"]
        self.assertTrue(result["available"])
        self.assertTrue(result["needs_review"])
        self.assertEqual(result["review_age_days"], 365)

    def test_invalid_segments_sources_and_evidence_fail_closed_per_company(self) -> None:
        mutations = [
            lambda entry: entry["revenue_breakdown"].update(total=1),
            lambda entry: entry["sources"][0].update(url="javascript:alert(1)"),
            lambda entry: entry["peers"][0].update(source_ids=["nonexistent"]),
            lambda entry: entry["evidence"][0].update(kind="certain_winner"),
            lambda entry: entry.update(sources=["not-a-source"]),
            lambda entry: entry.update(revenue_breakdown=[]),
        ]
        for change in mutations:
            with self.subTest(change=change), TemporaryDirectory() as directory:
                payload = deepcopy(self.catalog)
                change(payload["profiles"]["TRV"])
                path = Path(directory) / "catalog.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                result = load_company_catalog(path)
                self.assertIn("TRV", result["errors"])
                self.assertNotIn("TRV", result["profiles"])
                self.assertIn("FIX", result["profiles"])
                self.assertEqual(build_company_business("TRV", path=path)["reference"]["status"], "error")

    def test_broken_or_missing_catalog_preserves_personal_notes(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            for content in (None, "{not json", "[]"):
                with self.subTest(content=content):
                    if content is not None:
                        path.write_text(content, encoding="utf-8")
                    result = build_company_business("TRV", {"business_summary": "Saved by user"}, path=path)
                    self.assertEqual(result["summary"], "Saved by user")
                    self.assertEqual(result["reference"]["status"], "error")

    def test_file_update_is_seen_without_restarting_the_server(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(self.catalog), encoding="utf-8")
            before = build_company_business("TRV", path=path)["summary"]
            self.catalog["profiles"]["TRV"]["summary"] = "Updated sourced research"
            path.write_text(json.dumps(self.catalog), encoding="utf-8")
            after = build_company_business("TRV", path=path)["summary"]
            self.assertNotEqual(before, after)
            self.assertEqual(after, "Updated sourced research")


if __name__ == "__main__":
    unittest.main()
