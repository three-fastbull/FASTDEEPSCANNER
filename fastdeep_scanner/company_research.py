"""Sourced company facts are separate from the investor's private research journal."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .filing_extract import load_filing_profiles


CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "fastdeep_company_profiles.json"
# ข้อความจากแบบที่ยื่นต่อ SEC เติมได้เฉพาะช่องที่ยกมาตรง ๆ ได้
# Moat คู่เทียบและความเสี่ยงเป็นการตีความ จึงไม่อยู่ในรายการนี้
FILING_FIELDS = {
    "summary": "business_summary",
    "competitors": "competition",
    "key_customers": "customer_concentration",
}
# คำแปลไทยย่อจากข้อความชุดเดียวกัน จึงยังอ้างอิงไฟล์ที่ยื่นฉบับเดิมได้
THAI_FIELDS = {
    "summary": "summary_th",
    "revenue_model": "revenue_model_th",
    "key_customers": "customers_th",
    "competitors": "competition_th",
}
TEXT_FIELDS = {
    "summary": "business_summary",
    "revenue_model": "revenue_model",
    "revenue_segments": "revenue_segments",
    "key_customers": "key_customers",
    "competitors": "competitors",
    "moat_evidence": "moat_evidence",
    "catalysts": "catalysts",
    "risks": "risks",
    "invalidation": "invalidation",
    "source_urls": "source_urls",
}


def _http_url(value: Any) -> bool:
    try:
        url = urlsplit(str(value or ""))
        return url.scheme in {"http", "https"} and bool(url.hostname) and not url.username
    except ValueError:
        return False


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _valid_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_profile(symbol: str, entry: dict[str, Any]) -> None:
    for field in ("name", "period", "summary", "revenue_model", "key_customers", "moat_summary"):
        if not _text(entry.get(field)):
            raise ValueError(f"{symbol}: missing {field}")
    date.fromisoformat(entry["reviewed_at"])
    sources = entry.get("sources") or []
    if not isinstance(sources, list) or any(not isinstance(source, dict) for source in sources):
        raise ValueError(f"{symbol}: invalid source list")
    ids = {source["id"] for source in sources}
    if not sources or len(ids) != len(sources):
        raise ValueError(f"{symbol}: missing or duplicate sources")
    if any(not _http_url(source.get("url")) or not _text(source.get("title")) for source in sources):
        raise ValueError(f"{symbol}: invalid source")

    def check_sources(item: dict[str, Any]) -> None:
        cited = item.get("source_ids") or []
        if not isinstance(cited, list) or not cited or not set(cited) <= ids:
            raise ValueError(f"{symbol}: missing source reference")

    check_sources(entry)
    breakdown = entry["revenue_breakdown"]
    if not isinstance(breakdown, dict):
        raise ValueError(f"{symbol}: invalid business breakdown")
    check_sources(breakdown)
    segments = breakdown.get("segments") or []
    if not isinstance(segments, list) or not segments or any(not isinstance(segment, dict) for segment in segments) or not _text(breakdown.get("basis")):
        raise ValueError(f"{symbol}: missing business breakdown")
    total = breakdown.get("total")
    if total is not None:
        amounts = [segment.get("amount") for segment in segments]
        if not _valid_number(total) or total <= 0 or any(not _valid_number(n) or n < 0 for n in amounts):
            raise ValueError(f"{symbol}: invalid segment amounts")
        if not math.isclose(sum(amounts), total, rel_tol=0.0001, abs_tol=0.01):
            raise ValueError(f"{symbol}: segments do not reconcile with the stated total")
        if not _text(breakdown.get("currency")) or not _text(breakdown.get("unit")):
            raise ValueError(f"{symbol}: missing segment units")
    elif any(segment.get("amount") is not None for segment in segments):
        raise ValueError(f"{symbol}: amounts need a denominator")
    if any(not _text(segment.get("name")) for segment in segments):
        raise ValueError(f"{symbol}: missing segment name")
    if not entry.get("peers") or not entry.get("evidence"):
        raise ValueError(f"{symbol}: missing competition research")
    for peer in entry["peers"]:
        if not isinstance(peer, dict):
            raise ValueError(f"{symbol}: invalid peer")
        check_sources(peer)
        if any(not _text(peer.get(field)) for field in ("name", "overlap", "compare")):
            raise ValueError(f"{symbol}: incomplete peer comparison")
    for evidence in entry["evidence"]:
        if not isinstance(evidence, dict):
            raise ValueError(f"{symbol}: invalid evidence")
        check_sources(evidence)
        if evidence.get("kind") not in {"reported", "company_claim", "analysis"}:
            raise ValueError(f"{symbol}: evidence must distinguish fact from interpretation")
        if not _text(evidence.get("title")) or not _text(evidence.get("detail")):
            raise ValueError(f"{symbol}: incomplete evidence")


@lru_cache(maxsize=4)
def _read_catalog(path: str, modified: int, size: int) -> dict[str, Any]:
    # The file fingerprint invalidates the cache after a data-only update.
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("profiles"), dict):
        raise ValueError("Unsupported company research catalog")
    profiles: dict[str, Any] = {}
    aliases: dict[str, str] = {}
    errors: dict[str, str] = {}
    for symbol, entry in payload["profiles"].items():
        try:
            if symbol != symbol.strip().upper() or not isinstance(entry, dict):
                raise ValueError("Invalid company symbol")
            _validate_profile(symbol, entry)
            alternate_names = entry.get("aliases", [])
            if not isinstance(alternate_names, list):
                raise ValueError("Invalid company aliases")
            names = [symbol, *alternate_names]
            if any(not isinstance(name, str) or name != name.strip().upper() for name in names):
                raise ValueError("Invalid company alias")
            if len(set(names)) != len(names) or any(name in aliases for name in names):
                raise ValueError("Duplicate company alias")
            profiles[symbol] = entry
            aliases.update({name: symbol for name in names})
        except (KeyError, TypeError, ValueError) as exc:
            errors[symbol] = str(exc)
    return {"profiles": profiles, "aliases": aliases, "errors": errors}


def load_company_catalog(path: str | Path = CATALOG_PATH) -> dict[str, Any]:
    path = Path(path)
    try:
        stat = path.stat()
        return deepcopy(_read_catalog(str(path), stat.st_mtime_ns, stat.st_size))
    except (OSError, ValueError, TypeError) as exc:
        return {"profiles": {}, "aliases": {}, "errors": {"catalog": str(exc)}}


def build_company_business(
    symbol: str,
    research: dict[str, Any] | None = None,
    *,
    path: str | Path = CATALOG_PATH,
    today: date | None = None,
) -> dict[str, Any]:
    research = research or {}
    symbol = symbol.strip().upper()
    catalog = load_company_catalog(path)
    canonical = catalog["aliases"].get(symbol)
    entry = catalog["profiles"].get(canonical) or {}
    reference = deepcopy(entry)
    reference.update({
        "available": bool(entry),
        "symbol": canonical or symbol,
        "catalog_count": len(catalog["profiles"]),
        "status": "ready" if entry else "missing",
    })
    if symbol in catalog["errors"] or "catalog" in catalog["errors"]:
        reference["status"] = "error"
    if entry:
        age = max(0, ((today or date.today()) - date.fromisoformat(entry["reviewed_at"])).days)
        reference["needs_review"] = age > 180
        reference["review_age_days"] = age

    defaults = {key: _text(entry.get(key)) for key in TEXT_FIELDS}
    if entry:
        breakdown = reference["revenue_breakdown"]
        total = breakdown.get("total")
        lines = []
        for segment in breakdown["segments"]:
            segment["share_pct"] = round(segment["amount"] / total * 100, 2) if total else None
            share = f" {segment['share_pct']:.1f}%" if total else ""
            lines.append(f"{segment['name']}{share}: {segment.get('description', '')}".rstrip(": "))
        defaults["revenue_segments"] = "\n".join(lines)
        defaults["competitors"] = "\n".join(
            f"{peer['name']}: {peer['overlap']} | {peer['compare']}" for peer in entry["peers"]
        )
        defaults["moat_evidence"] = entry["moat_summary"]
        defaults["source_urls"] = "\n".join(source["url"] for source in entry["sources"])

    filing = load_filing_profiles().get(symbol) or {}
    filing_defaults = {
        key: _text(filing.get(source_key)) for key, source_key in FILING_FIELDS.items()
    }
    # คำแปลไทยย่อจากข้อความเดียวกัน อ่านง่ายกว่าต้นฉบับอังกฤษ จึงใช้ก่อนถ้ามี
    thai = filing.get("thai") or {}
    for key, thai_key in THAI_FIELDS.items():
        translated = _text(thai.get(thai_key))
        if translated:
            filing_defaults[key] = translated
    if filing.get("source_url"):
        filing_defaults["source_urls"] = _text(filing["source_url"])

    business: dict[str, Any] = {"field_origins": {}}
    for key, journal_key in TEXT_FIELDS.items():
        manual = _text(research.get(journal_key))
        from_filing = filing_defaults.get(key, "")
        # ลำดับความน่าเชื่อถือ: บันทึกของนักลงทุน > แคตตาล็อกที่ทบทวนแล้ว > ข้อความจากแบบ
        business[key] = manual or defaults[key] or from_filing
        if manual:
            origin = "journal"
        elif defaults[key]:
            origin = "reference"
        elif from_filing:
            origin = "filing"
        else:
            origin = "missing"
        business["field_origins"][key] = origin
    business["reference"] = reference
    business["filing"] = {
        "available": bool(filing),
        "entity_name": _text(filing.get("entity_name")),
        "industry": _text(filing.get("industry")),
        "form": _text(filing.get("form")),
        "filed_at": _text(filing.get("filed_at")),
        "period": _text(filing.get("period")),
        "source_url": _text(filing.get("source_url")) if _http_url(filing.get("source_url")) else "",
        "language": "th" if thai.get("summary_th") else (_text(filing.get("language")) or "en"),
        "translated": bool(thai.get("summary_th")),
        "model": _text(thai.get("model")),
        "found": filing.get("found") or {},
    }
    # Reference material never supplies the user's Moat rating, thesis, or approval.
    business["verified"] = bool(research.get("company_profile_verified"))
    business["has_details"] = bool(business["summary"] and business["competitors"])
    return business
