from __future__ import annotations

import json
import math
import gzip
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4


from .local_config import get_setting


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_TICKER_LOOKUP_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}"
    "&type=10-K&dateb=&owner=include&count=10&output=atom"
)
# SEC ต้องการอีเมลที่ติดต่อกลับได้จริงในทุก request และปฏิเสธที่อยู่ประเภท
# noreply ด้วย 403 ทันที ค่าติดต่อจึงเก็บไว้ใน .env ของเครื่อง ไม่ฝังในซอร์ส
SEC_CONTACT_SETTING = "FASTDEEP_SEC_CONTACT"
SEC_USER_AGENT_SETTING = "FASTDEEP_SEC_USER_AGENT"
APPLICATION_NAME = "FastDeep Intelligence Platform"
UNREACHABLE_EMAIL_DOMAINS = ("noreply", "no-reply", "example.com", "localhost")
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
QUARTERLY_FORMS = {"10-Q", "10-Q/A"}
TRANSITION_FORMS = {"10-KT", "10-KT/A", "10-QT", "10-QT/A"}
NORMALIZER_VERSION = 4


class SecEdgarError(RuntimeError):
    """Raised when SEC EDGAR cannot supply usable company facts."""


# The first matching standard concept wins for a period. Older concepts remain
# as fallbacks because issuers can change taxonomy versions between filings.
SEC_CONCEPTS: dict[str, tuple[str, ...]] = {
    "total_revenue": (
        "Revenues",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueGoodsNet",
        "OperatingRevenues",
    ),
    "cost_of_revenue": (
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
    ),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "pretax_income": (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxes",
    ),
    "tax_provision": ("IncomeTaxExpenseBenefit",),
    "net_income": (
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ),
    "basic_eps": ("EarningsPerShareBasic",),
    "total_assets": ("Assets",),
    "current_assets": ("AssetsCurrent",),
    "total_liabilities": ("Liabilities",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "total_debt": (
        "LongTermDebtAndFinanceLeaseObligations",
        "LongTermDebtAndCapitalLeaseObligations",
    ),
    "_debt_current": (
        "LongTermDebtAndFinanceLeaseObligationsCurrent",
        "LongTermDebtAndCapitalLeaseObligationsCurrent",
        "LongTermDebtCurrent",
    ),
    "_debt_noncurrent": (
        "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
        "LongTermDebtAndCapitalLeaseObligationsNoncurrent",
        "LongTermDebtNoncurrent",
    ),
    "_short_term_borrowings": ("ShortTermBorrowings", "ShortTermDebtCurrent"),
    "stockholders_equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "PartnersCapital",
    ),
    "cash_and_equivalents": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "CashAndDueFromBanks",
    ),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capital_expenditure": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForAdditionsToPropertyPlantAndEquipment",
    ),
}

IFRS_CONCEPTS: dict[str, tuple[str, ...]] = {
    "total_revenue": ("Revenue",),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("ProfitLossFromOperatingActivities",),
    "pretax_income": ("ProfitLossBeforeTax",),
    "tax_provision": ("IncomeTaxExpenseContinuingOperations", "IncomeTaxExpense"),
    "net_income": ("ProfitLoss",),
    "basic_eps": ("BasicEarningsLossPerShare",),
    "total_assets": ("Assets",),
    "current_assets": ("CurrentAssets",),
    "total_liabilities": ("Liabilities",),
    "current_liabilities": ("CurrentLiabilities",),
    "stockholders_equity": ("Equity", "EquityAttributableToOwnersOfParent"),
    "cash_and_equivalents": ("CashAndCashEquivalents",),
    "operating_cash_flow": ("CashFlowsFromUsedInOperatingActivities",),
    "capital_expenditure": ("PurchaseOfPropertyPlantAndEquipment",),
}

FLOW_METRICS = {
    "total_revenue",
    "cost_of_revenue",
    "gross_profit",
    "operating_income",
    "pretax_income",
    "tax_provision",
    "net_income",
    "basic_eps",
    "operating_cash_flow",
    "capital_expenditure",
}
CUMULATIVE_QUARTER_METRICS = {"operating_cash_flow", "capital_expenditure"}
INTERNAL_METRICS = {"_debt_current", "_debt_noncurrent", "_short_term_borrowings"}


def _sec_contact() -> str:
    return get_setting(SEC_CONTACT_SETTING)


def _sec_user_agent() -> str:
    """``ชื่อแอป อีเมลติดต่อ`` ตามรูปแบบที่ SEC กำหนด

    ถ้ายังไม่ได้ตั้งค่า ให้หยุดพร้อมบอกวิธีแก้ ดีกว่าปล่อยให้ยิงไปโดน 403
    ทั้งชุดแล้วเข้าใจว่าเป็นปัญหาเครือข่าย
    """
    configured = get_setting(SEC_USER_AGENT_SETTING)
    if configured:
        return configured
    contact = _sec_contact()
    if not contact:
        raise SecEdgarError(
            f"ยังไม่ได้ตั้งอีเมลติดต่อสำหรับ SEC EDGAR ให้เพิ่มบรรทัด {SEC_CONTACT_SETTING}=อีเมลของคุณ "
            "ในไฟล์ .env ที่รากโปรเจกต์ SEC บังคับให้ทุก request ระบุอีเมลที่ติดต่อกลับได้จริง"
        )
    lowered = contact.lower()
    if any(marker in lowered for marker in UNREACHABLE_EMAIL_DOMAINS):
        raise SecEdgarError(
            f"SEC EDGAR ปฏิเสธอีเมลที่ติดต่อกลับไม่ได้ ({contact}) "
            f"ให้ตั้ง {SEC_CONTACT_SETTING} ในไฟล์ .env เป็นอีเมลจริงที่เปิดอ่านได้"
        )
    return f"{APPLICATION_NAME} {contact}"


def _download_json(url: str, timeout: int = 30) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": _sec_user_agent(),
            "From": _sec_contact(),
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise SecEdgarError(
                f"SEC EDGAR ตอบ 403 และปฏิเสธอีเมลที่ประกาศไว้ ({_sec_contact() or 'ยังไม่ได้ตั้งค่า'}) "
                f"ให้ตั้ง {SEC_CONTACT_SETTING} ในไฟล์ .env เป็นอีเมลจริงที่ติดต่อกลับได้ "
                "SEC บล็อกที่อยู่ประเภท noreply ทันที"
            ) from exc
        if exc.code == 429:
            raise SecEdgarError("SEC EDGAR จำกัดความถี่ชั่วคราว (429) โปรดลองใหม่ภายหลัง") from exc
        raise


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def load_sec_ticker_map(
    cache_path: str | Path,
    *,
    refresh: bool = False,
    max_age_hours: int = 24,
    timeout: int = 30,
) -> dict[str, dict[str, Any]]:
    path = Path(cache_path)
    payload: dict[str, Any] | None = None
    if path.exists() and not refresh:
        age_seconds = time.time() - path.stat().st_mtime
        if age_seconds <= max_age_hours * 3600:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = None
    if payload is None:
        payload = _download_json(SEC_TICKERS_URL, timeout=timeout)
        _write_json_atomic(path, payload)

    result: dict[str, dict[str, Any]] = {}
    for item in payload.values():
        ticker = str(item.get("ticker") or "").upper()
        cik = item.get("cik_str")
        if not ticker or cik is None:
            continue
        result[ticker] = {
            "cik": str(cik).zfill(10),
            "title": str(item.get("title") or ticker),
        }
    return result


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _duration_days(item: dict[str, Any]) -> int | None:
    start = _parse_date(item.get("start"))
    end = _parse_date(item.get("end"))
    return (end - start).days if start and end else None


def _filing_delay_days(item: dict[str, Any]) -> int | None:
    end = _parse_date(item.get("end"))
    filed = _parse_date(item.get("filed"))
    return (filed - end).days if end and filed else None


def _is_currency_unit(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{3}", value))


def _taxonomy_concepts(payload: dict[str, Any]) -> list[tuple[str, dict[str, tuple[str, ...]]]]:
    facts = payload.get("facts") or {}
    output: list[tuple[str, dict[str, tuple[str, ...]]]] = []
    if facts.get("us-gaap"):
        output.append(("us-gaap", SEC_CONCEPTS))
    if facts.get("ifrs-full"):
        output.append(("ifrs-full", IFRS_CONCEPTS))
    return output


def _detect_currency(payload: dict[str, Any]) -> str:
    dates: dict[str, set[tuple[str, str]]] = {}
    facts = payload.get("facts") or {}
    for taxonomy, mappings in _taxonomy_concepts(payload):
        taxonomy_facts = facts.get(taxonomy) or {}
        for metric in ("total_revenue", "total_assets", "net_income"):
            for concept in mappings.get(metric, ()):
                for unit, values in (taxonomy_facts.get(concept) or {}).get("units", {}).items():
                    if not _is_currency_unit(unit):
                        continue
                    for item in values:
                        if (str(item.get("form") or "") in ANNUAL_FORMS | QUARTERLY_FORMS | TRANSITION_FORMS
                                and _parse_date(item.get("end"))):
                            dates.setdefault(unit, set()).add((item["end"], metric))
    if not dates:
        return "USD"
    # A former reporting currency can have many more historical facts than
    # the current one. Prefer the most recent financial period, never mix units.
    latest = {unit: max(end for end, _ in records) for unit, records in dates.items()}
    return max(dates, key=lambda unit: (latest[unit],
               sum(end == latest[unit] for end, _ in dates[unit]), len(dates[unit]), unit == "USD"))


def _unit_values(node: dict[str, Any], metric: str, currency: str) -> list[dict[str, Any]]:
    units = node.get("units") or {}
    if metric == "basic_eps":
        preferred = [f"{currency}/shares", f"{currency}/share"]
        preferred.extend(unit for unit in units if currency in unit and "share" in unit.lower())
    else:
        preferred = [currency]
    for unit in preferred:
        if units.get(unit):
            return list(units[unit])
    return []


def _valid_annual(item: dict[str, Any], metric: str) -> bool:
    if str(item.get("form") or "") not in ANNUAL_FORMS:
        return False
    delay = _filing_delay_days(item)
    if delay is None or delay < 0:
        return False
    duration = _duration_days(item)
    if metric in FLOW_METRICS and (duration is None or not 330 <= duration <= 400):
        return False
    return bool(item.get("end"))


def _valid_quarter(item: dict[str, Any], metric: str) -> bool:
    if str(item.get("form") or "") not in QUARTERLY_FORMS | ANNUAL_FORMS:
        return False
    delay = _filing_delay_days(item)
    if delay is None or delay < 0:
        return False
    duration = _duration_days(item)
    if metric in FLOW_METRICS and (duration is None or not 45 <= duration <= 310):
        return False
    return bool(item.get("end"))


def _fact_score(item: dict[str, Any], metric: str, *, annual: bool) -> tuple[str, int, str]:
    duration = _duration_days(item) or 0
    if annual or metric in CUMULATIVE_QUARTER_METRICS:
        duration_score = duration
    elif metric in FLOW_METRICS:
        duration_score = -abs(duration - 91)
    else:
        duration_score = 0
    return str(item.get("filed") or ""), duration_score, str(item.get("accn") or "")


def _filing_url(cik: str, accession: str) -> str:
    if not accession:
        return ""
    compact = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{compact}/{accession}-index.html"


def _period_bucket(item: dict[str, Any], cik: str, quarter: str | None = None) -> dict[str, Any]:
    fiscal_year = str(item.get("fy") or str(item.get("end") or "")[:4])
    output: dict[str, Any] = {
        "period_end": str(item.get("end") or ""),
        "fiscal_year": fiscal_year,
        "metrics": {},
        "_metric_meta": {},
        "source_form": str(item.get("form") or ""),
        "accession": str(item.get("accn") or ""),
        "filed_at": str(item.get("filed") or ""),
    }
    if quarter:
        output["quarter"] = quarter
    output["source_url"] = _filing_url(cik, output["accession"])
    return output


def _put_metric(
    bucket: dict[str, Any],
    metric: str,
    item: dict[str, Any],
    value: float,
    cik: str,
) -> None:
    bucket["metrics"][metric] = value
    bucket["_metric_meta"][metric] = {
        "start": item.get("start"),
        "duration_days": _duration_days(item),
        "raw_value": value,
    }
    bucket.setdefault("metric_sources", {})[metric] = {
        "kind": "reported",
        "concept": item.get("_concept"),
        "period_start": item.get("start"),
        "period_end": item.get("end"),
        "filed_at": item.get("filed"),
        "source_form": item.get("form"),
        "source_url": _filing_url(cik, str(item.get("accn") or "")),
    }
    if str(item.get("filed") or "") >= str(bucket.get("filed_at") or ""):
        bucket["source_form"] = str(item.get("form") or "")
        bucket["accession"] = str(item.get("accn") or "")
        bucket["filed_at"] = str(item.get("filed") or "")
        bucket["source_url"] = _filing_url(cik, bucket["accession"])


def _derive_metrics(period: dict[str, Any]) -> None:
    metrics = period["metrics"]
    if metrics.get("total_liabilities") is None:
        assets = metrics.get("total_assets")
        equity = metrics.get("stockholders_equity")
        if assets is not None and equity is not None:
            metrics["total_liabilities"] = assets - equity
    if metrics.get("total_debt") is None:
        components = [metrics.get(key) for key in INTERNAL_METRICS]
        present = [value for value in components if value is not None]
        if present:
            metrics["total_debt"] = sum(present)
    if metrics.get("gross_profit") is None:
        revenue = metrics.get("total_revenue")
        cost = metrics.get("cost_of_revenue")
        if revenue is not None and cost is not None:
            metrics["gross_profit"] = revenue - cost
    if metrics.get("capital_expenditure") is not None:
        metrics["capital_expenditure"] = -abs(metrics["capital_expenditure"])
    operating_cash = metrics.get("operating_cash_flow")
    capex = metrics.get("capital_expenditure")
    if operating_cash is not None and capex is not None:
        metrics["free_cash_flow"] = operating_cash + capex
        period.setdefault("metric_sources", {})["free_cash_flow"] = {
            "kind": "derived_free_cash_flow",
            "inputs": [(period.get("metric_sources") or {}).get(key)
                       for key in ("operating_cash_flow", "capital_expenditure")],
            "source_url": period.get("source_url"),
        }
        period.setdefault("derived_metrics", []).append("free_cash_flow")
    for metric in INTERNAL_METRICS:
        metrics.pop(metric, None)


def _fiscal_calendar(
    records: dict[str, list[tuple[int, dict[str, Any]]]],
) -> dict[str, dict[str, Any]]:
    # fy/fp identify the filing, not necessarily the comparative fact's year.
    # Only a full-year flow can anchor an annual period; instants cannot.
    spans: dict[str, dict[str, set[str]]] = {}
    filing_ends: dict[str, str] = {}
    annual_facts: list[dict[str, Any]] = []
    for metric in sorted(FLOW_METRICS):
        for _, item in records.get(metric, []):
            if not _valid_annual(item, metric):
                continue
            end, start = str(item["end"]), str(item["start"])
            spans.setdefault(end, {}).setdefault(start, set()).add(metric)
            accession = str(item.get("accn") or "")
            filing_ends[accession] = max(filing_ends.get(accession, ""), end)
            annual_facts.append(item)
    if not spans:
        return {}
    latest = date.fromisoformat(max(spans))
    votes: dict[str, int] = {}
    for item in annual_facts:
        accession = str(item.get("accn") or "")
        end = date.fromisoformat(item["end"])
        try:
            fiscal_year = int(item.get("fy"))
        except (TypeError, ValueError):
            continue
        if (item["end"] != filing_ends[accession]
                or (_filing_delay_days(item) or 0) > 300
                or not 0 <= (latest - end).days <= 365 * 8
                or abs(fiscal_year - end.year) > 1):
            continue
        votes[accession] = fiscal_year + round((latest - end).days / 365.2425)
    latest_year = Counter(votes.values()).most_common(1)[0][0] if votes else latest.year
    calendar = {
        end: {
            "period_end": end,
            "period_start": max(starts, key=lambda start: (len(starts[start]), start)),
            "fiscal_year": str(latest_year - round((latest - date.fromisoformat(end)).days / 365.2425)),
        }
        for end, starts in sorted(spans.items())
    }
    # Some issuers re-present a 52-week year with a date one day away. Those
    # are alternative versions of one year, not additional annual statements.
    latest_filed = {end: max(str(item.get("filed") or "") for item in annual_facts if item["end"] == end)
                    for end in calendar}
    kept: dict[str, dict[str, Any]] = {}
    for end, period in calendar.items():
        duplicate = next((key for key, current in kept.items()
                          if current["fiscal_year"] == period["fiscal_year"]
                          and abs((date.fromisoformat(key) - date.fromisoformat(end)).days) <= 7), None)
        if duplicate is not None:
            if latest_filed[duplicate] > latest_filed[end]:
                continue
            kept.pop(duplicate)
        kept[end] = period
    return kept


def _quarter_position(end: str, calendar: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    point = _parse_date(end)
    if point is None or not calendar:
        return None
    for annual in calendar.values():
        start = date.fromisoformat(annual["period_start"])
        finish = date.fromisoformat(annual["period_end"])
        if start <= point <= finish:
            quarter = max(1, round(((point - start).days + 1) / ((finish - start).days + 1) * 4))
            if quarter > 4 or (quarter == 4 and point != finish):
                return None
            return {** annual, "quarter": f"Q{quarter}", "fiscal_start": annual["period_start"]}
    latest = calendar[max(calendar)]
    elapsed = (point - date.fromisoformat(latest["period_end"])).days
    if 45 <= elapsed <= 310:
        return {
            "fiscal_year": str(int(latest["fiscal_year"]) + 1),
            "quarter": f"Q{max(1, min(3, round(elapsed / 91.31)))}",
            "fiscal_start": (date.fromisoformat(latest["period_end"]) + timedelta(days=1)).isoformat(),
        }
    return None


def _extract_company_periods(
    payload: dict[str, Any],
    *,
    cik: str,
    currency: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    facts = payload.get("facts") or {}
    records: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for taxonomy, mappings in _taxonomy_concepts(payload):
        taxonomy_facts = facts.get(taxonomy) or {}
        for metric, concepts in mappings.items():
            for concept_priority, concept in enumerate(concepts):
                for item in _unit_values(taxonomy_facts.get(concept) or {}, metric, currency):
                    try:
                        usable = math.isfinite(float(item.get("val")))
                    except (TypeError, ValueError):
                        usable = False
                    if usable and _parse_date(item.get("end")):
                        priority = concept_priority + (100 if taxonomy == "ifrs-full" else 0)
                        records.setdefault(metric, []).append((priority, {**item, "_concept": f"{taxonomy}:{concept}"}))

    calendar = _fiscal_calendar(records)
    anchors: dict[str, set[str]] = {}
    for metric in sorted(FLOW_METRICS):
        for _, item in records.get(metric, []):
            duration = _duration_days(item)
            if (_valid_quarter(item, metric) and duration is not None
                    and 45 <= duration <= 135 and _quarter_position(item["end"], calendar)):
                anchors.setdefault(item["end"], set()).add(metric)
    quarter_ends: dict[tuple[str, str], str] = {}
    for end in sorted(anchors):
        position = _quarter_position(end, calendar)
        key = (position["fiscal_year"], position["quarter"])
        current = quarter_ends.get(key)
        if current is None or (len(anchors[end]), end) > (len(anchors[current]), current):
            quarter_ends[key] = end

    annual_buckets: dict[str, dict[str, Any]] = {}
    quarter_buckets: dict[str, dict[str, Any]] = {}
    for metric, values in records.items():
        for annual_mode, ends, buckets in (
            (True, set(calendar), annual_buckets),
            (False, set(quarter_ends.values()), quarter_buckets),
        ):
            selected: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {}
            for priority, item in values:
                end = item["end"]
                if end not in ends:
                    continue
                valid = _valid_annual(item, metric) if annual_mode else _valid_quarter(item, metric)
                if not valid:
                    continue
                position = calendar[end] if annual_mode else _quarter_position(end, calendar)
                duration = _duration_days(item) or 0
                if not annual_mode and metric in {"total_revenue", "net_income"}:
                    annual_end = position.get("period_end")
                    reference = (annual_buckets.get(annual_end, {}).get("metric_sources", {}).get(metric) or {}).get("concept")
                    if reference and item.get("_concept") != reference:
                        continue
                if metric in FLOW_METRICS:
                    expected_start = position["period_start"] if annual_mode else position["fiscal_start"]
                    if annual_mode and item.get("start") != expected_start:
                        continue
                    if not annual_mode and duration > 135 and (
                        metric == "basic_eps" or item.get("start") != expected_start
                    ):
                        continue
                direct = annual_mode or metric not in FLOW_METRICS or duration <= 135
                rank = (int(direct), -priority, *_fact_score(item, metric, annual=annual_mode))
                if end not in selected or rank > selected[end][0]:
                    selected[end] = (rank, item)
            for end, (_, item) in selected.items():
                position = calendar[end] if annual_mode else _quarter_position(end, calendar)
                bucket = buckets.setdefault(end, _period_bucket(item, cik, position.get("quarter")))
                bucket["fiscal_year"] = position["fiscal_year"]
                if annual_mode:
                    bucket["period_start"] = position["period_start"]
                else:
                    number = int(position["quarter"][1])
                    previous_end = quarter_ends.get((position["fiscal_year"], f"Q{number - 1}"))
                    bucket["period_start"] = (
                        (date.fromisoformat(previous_end) + timedelta(days=1)).isoformat()
                        if previous_end else position["fiscal_start"] if number == 1 else None
                    )
                _put_metric(bucket, metric, item, float(item["val"]), cik)

    annual = sorted(annual_buckets.values(), key=lambda item: item["period_end"])
    quarters = sorted(quarter_buckets.values(), key=lambda item: item["period_end"])
    by_year: dict[str, dict[str, dict[str, Any]]] = {}
    for period in quarters:
        by_year.setdefault(period["fiscal_year"], {})[period["quarter"]] = period
    for periods in by_year.values():
        for metric in sorted(FLOW_METRICS - {"basic_eps"}):
            for number in (2, 3, 4):
                period = periods.get(f"Q{number}")
                if not period or metric not in period["metrics"]:
                    continue
                meta = period["_metric_meta"].get(metric) or {}
                if int(meta.get("duration_days") or 0) <= 135:
                    continue
                previous = periods.get(f"Q{number - 1}") or {}
                prior = (previous.get("_metric_meta") or {}).get(metric) or {}
                if prior and prior.get("start") == meta.get("start"):
                    period["metrics"][metric] = meta["raw_value"] - prior["raw_value"]
                    source = period["metric_sources"][metric]
                    inputs = [dict(source), (previous.get("metric_sources") or {}).get(metric)]
                    source["kind"] = "derived_ytd_difference"
                    source["inputs"] = inputs
                    period.setdefault("derived_metrics", []).append(metric)
                else:
                    # Nine-month cash flow minus Q1 is not Q3 cash flow.
                    period["metrics"].pop(metric, None)
                    period["metric_sources"].pop(metric, None)

    for period in annual + quarters:
        _derive_metrics(period)
        period.pop("_metric_meta", None)
    annual = [period for period in annual if len(period["metrics"]) >= 3]
    quarters = [period for period in quarters if len(period["metrics"]) >= 2]
    return annual, quarters


def normalize_companyfacts(payload: dict[str, Any], *, symbol: str, cik: str) -> dict[str, Any]:
    currency = _detect_currency(payload)
    annual, quarterly = _extract_company_periods(payload, cik=cik, currency=currency)
    if not annual:
        raise SecEdgarError(f"SEC EDGAR ไม่มีงบมาตรฐานที่ใช้ได้สำหรับ {symbol}")
    excluded: dict[tuple[str, str], dict[str, Any]] = {}
    latest_annual = max(period["period_end"] for period in annual)
    for taxonomy, mappings in _taxonomy_concepts(payload):
        for metric in ("total_revenue", "net_income", "operating_cash_flow"):
            for concept in mappings.get(metric, ()):
                node = payload["facts"][taxonomy].get(concept) or {}
                for item in _unit_values(node, metric, currency):
                    form, end = str(item.get("form") or ""), str(item.get("end") or "")
                    if (form not in ANNUAL_FORMS | TRANSITION_FORMS or end <= latest_annual
                            or _duration_days(item) is None or (_filing_delay_days(item) or -1) < 0):
                        continue
                    if not _valid_annual(item, metric):
                        excluded[(end, form)] = {
                            "period_start": item.get("start"), "period_end": end,
                            "source_form": form, "duration_days": _duration_days(item),
                            "source_url": _filing_url(cik, str(item.get("accn") or "")),
                        }
    return {
        "symbol": symbol,
        "cik": cik,
        "entity_name": str(payload.get("entityName") or symbol),
        "currency": currency,
        "annual": annual,
        "quarterly": quarterly,
        "source": "SEC EDGAR companyfacts (10-K/10-Q XBRL)",
        "source_url": f"https://www.sec.gov/edgar/browse/?CIK={int(cik)}",
        "normalizer_version": NORMALIZER_VERSION,
        "excluded_periods": list(excluded.values()),
    }


def lookup_cik_from_edgar(symbol: str, *, timeout: int = 30) -> str | None:
    """ถาม EDGAR ตรง ๆ ว่า ticker นี้ยื่น 10-K ภายใต้ CIK ไหน

    ``company_tickers.json`` ไม่ครอบคลุมทุกบริษัท และบางครั้งชี้ไปที่นิติบุคคล
    ใหม่ที่ยังไม่มีประวัติงบ เช่น XOM ที่ถูกแมปไปยังบริษัทโฮลดิ้งที่เพิ่งจดทะเบียน
    ส่วนการค้นหาของ EDGAR จะคืน CIK ของผู้ยื่นแบบจริง
    """
    ticker = symbol.strip().upper().replace(".", "-")
    if not ticker:
        return None
    request = urllib.request.Request(
        SEC_TICKER_LOOKUP_URL.format(ticker=urllib.parse.quote(ticker, safe="")),
        headers={
            "User-Agent": _sec_user_agent(),
            "From": _sec_contact(),
            "Accept": "application/atom+xml",
            "Accept-Encoding": "identity",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - ทางสำรอง ล้มได้โดยไม่ทำให้ทั้งงานพัง
        return None
    found = re.findall(r"CIK=(\d{10})", body)
    return found[0] if found else None


def _companyfacts_for_cik(symbol: str, cik: str, timeout: int) -> dict[str, Any]:
    try:
        payload = _download_json(SEC_COMPANYFACTS_URL.format(cik=cik), timeout=timeout)
    except SecEdgarError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SecEdgarError(f"ดึง SEC Company Facts ของ {symbol} ไม่สำเร็จ: {exc}") from exc
    snapshot = Path(__file__).resolve().parent.parent / "storage" / "sec_companyfacts" / f"CIK{cik}.json.gz"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    temporary = snapshot.with_name(f".{snapshot.name}.{uuid4().hex}.tmp")
    temporary.write_bytes(gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"), compresslevel=1))
    temporary.replace(snapshot)
    return normalize_companyfacts(payload, symbol=symbol, cik=cik)


# งบชุดที่ล่าสุดเก่ากว่านี้ถือว่านิติบุคคลนั้นเลิกยื่นแล้ว
STALE_FILING_MONTHS = 18


def _latest_period(normalized: dict[str, Any] | None) -> str:
    periods = (normalized or {}).get("annual") or []
    return max((str(period.get("period_end") or "") for period in periods), default="")


def _better_filing_history(
    current: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """เลือกชุดที่ยังยื่นอยู่ก่อน แล้วจึงดูว่าชุดไหนย้อนหลังได้ยาวกว่า

    บริษัทที่ปรับโครงสร้างจะทิ้งนิติบุคคลเก่าที่มีประวัติยาวแต่หยุดยื่นไปแล้ว
    การเลือกชุดที่ยาวกว่าอย่างเดียวจึงเคยดึงงบปี 2023 มาใช้กับราคาปี 2026
    """
    if current is None:
        return candidate
    if candidate is None:
        return current

    cutoff = (date.today() - timedelta(days=STALE_FILING_MONTHS * 30)).isoformat()
    current_live = _latest_period(current) >= cutoff
    candidate_live = _latest_period(candidate) >= cutoff
    if current_live != candidate_live:
        return current if current_live else candidate

    current_years = len(current.get("annual") or [])
    candidate_years = len(candidate.get("annual") or [])
    if candidate_years != current_years:
        return candidate if candidate_years > current_years else current
    return candidate if _latest_period(candidate) > _latest_period(current) else current


def fetch_sec_companyfacts(
    symbol: str,
    *,
    ticker_map: dict[str, dict[str, Any]],
    timeout: int = 30,
    minimum_years: int = 5,
) -> dict[str, Any]:
    """งบจากนิติบุคคลที่ยื่นภายใต้ ticker นี้และมีประวัติยาวที่สุด

    ``company_tickers.json`` ชี้ไปที่ผู้จดทะเบียนล่าสุดของ ticker นั้น ซึ่งบางครั้ง
    เป็นบริษัทโฮลดิ้งที่เพิ่งตั้ง (XOM), เอนทิตีที่ปรับโครงสร้างใหม่ (BLK) หรือ
    บริษัทลูกที่เป็นห้างหุ้นส่วน (EQR) ทั้งสามกรณีให้ประวัติสั้นกว่าความเป็นจริงมาก
    จึงเทียบกับผลจากการค้นหาของ EDGAR แล้วเลือกชุดที่ยาวกว่า
    """
    ticker = symbol.strip().upper().replace(".", "-")
    identity = ticker_map.get(ticker)
    mapped_cik = str(identity["cik"]).zfill(10) if identity else None
    best: dict[str, Any] | None = None
    first_error: SecEdgarError | None = None

    if mapped_cik:
        try:
            best = _companyfacts_for_cik(symbol, mapped_cik, timeout)
        except SecEdgarError as exc:
            first_error = exc

    # ประวัติครบตามเป้าแล้วก็ไม่ต้องยิงเพิ่ม ค่าใช้จ่ายนี้จึงตกเฉพาะตัวที่สั้นผิดปกติ
    if best is not None and len(best.get("annual") or []) >= minimum_years:
        return best

    fallback_cik = lookup_cik_from_edgar(symbol, timeout=timeout)
    if fallback_cik and fallback_cik != mapped_cik:
        try:
            candidate = _companyfacts_for_cik(symbol, fallback_cik, timeout)
        except SecEdgarError as exc:
            first_error = first_error or exc
        else:
            best = _better_filing_history(best, candidate)

    if best is not None:
        return best
    if first_error:
        raise first_error
    raise SecEdgarError(f"ไม่พบ CIK ของ {symbol} ทั้งในรายการ ticker และการค้นหาของ SEC")
