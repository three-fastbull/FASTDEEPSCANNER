"""คัดหุ้นจากเมกะเทรนด์และกลุ่มอุตสาหกรรม

ต่างจากหน้า Scanner ที่คัดจากรูปแบบราคา หน้านี้เริ่มจากคำถามว่า "อยากลงทุนใน
เทรนด์ไหน" แล้วค่อยไล่ดูบริษัทในเทรนด์นั้น ตรงกับวิธี Top-Down ในหลักสูตร

สถานะคุณภาพของแต่ละบริษัทมาจากงบที่ยืนยันแล้ว จึงบอกได้ทันทีว่าตัวไหนน่าไปตรวจ
ต่อ โดยไม่ต้องเปิดทีละตัว
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from .company_research import load_company_catalog
from .data_io import _financial_cache_path, load_market_data
from .filing_extract import load_filing_profiles
from .megatrends import UNCLASSIFIED, INDUSTRY_LABELS, build_catalog, classify_industry, megatrends_for


def _quality_snapshot(symbol: str, financials: dict[str, Any] | None) -> dict[str, Any]:
    """ตัวเลขคุณภาพย่อ ๆ พอให้ตัดสินใจว่าจะเปิดดูตัวไหนต่อ"""
    annual = (financials or {}).get("annual") or []
    if len(annual) < 2:
        return {"statements": len(annual), "roe": None, "revenue_cagr": None, "debt_to_equity": None}
    first, latest = annual[0], annual[-1]
    revenue_first = (first.get("metrics") or {}).get("total_revenue")
    revenue_last = (latest.get("metrics") or {}).get("total_revenue")
    years = max(1, len(annual) - 1)
    cagr = None
    if revenue_first and revenue_last and revenue_first > 0 and revenue_last > 0:
        cagr = round(((revenue_last / revenue_first) ** (1 / years) - 1) * 100, 1)
    ratios = latest.get("ratios") or {}
    return {
        "statements": len(annual),
        "period": str(latest.get("period_end") or "")[:10],
        "roe": round(ratios["roe"], 1) if ratios.get("roe") is not None else None,
        "debt_to_equity": round(ratios["debt_to_equity"], 2) if ratios.get("debt_to_equity") is not None else None,
        "net_margin": round(ratios["net_margin"], 1) if ratios.get("net_margin") is not None else None,
        "revenue_cagr": cagr,
    }


def build_screener(*, market: str = "US") -> dict[str, Any]:
    filings = load_filing_profiles()
    catalog = load_company_catalog()
    _, fundamentals = load_market_data()
    reviewed = set(catalog["profiles"])

    companies: list[dict[str, Any]] = []
    for symbol, filing in sorted(filings.items()):
        snapshot = fundamentals.get(symbol)
        if snapshot is None:
            continue
        if market != "ALL" and (snapshot.market or "").upper() != market.upper():
            continue
        industry = filing.get("industry") or ""
        group = classify_industry(industry)
        financials = None
        path = _financial_cache_path(symbol)
        if path.exists():
            try:
                financials = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                financials = None

        companies.append(
            {
                "symbol": symbol,
                "name": snapshot.name or filing.get("entity_name") or symbol,
                "market": snapshot.market,
                "industry": industry,
                "industry_group": group,
                "industry_label": INDUSTRY_LABELS.get(group, "อื่น ๆ ที่ยังไม่จัดกลุ่ม"),
                "megatrends": megatrends_for(group),
                "has_business_text": bool((filing.get("found") or {}).get("business_summary")),
                "reviewed": symbol in reviewed,
                "source_url": filing.get("source_url") or "",
                "quality": _quality_snapshot(symbol, financials),
            }
        )

    payload = build_catalog(companies)
    payload["companies"] = companies
    payload["generated_at"] = date.today().isoformat()
    payload["market"] = market
    return payload
