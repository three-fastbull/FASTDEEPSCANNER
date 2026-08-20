from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any


from .local_config import get_setting


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
# SEC ต้องการอีเมลที่ติดต่อกลับได้จริงในทุก request และปฏิเสธที่อยู่ประเภท
# noreply ด้วย 403 ทันที ค่าติดต่อจึงเก็บไว้ใน .env ของเครื่อง ไม่ฝังในซอร์ส
SEC_CONTACT_SETTING = "FASTDEEP_SEC_CONTACT"
SEC_USER_AGENT_SETTING = "FASTDEEP_SEC_USER_AGENT"
APPLICATION_NAME = "FastDeep Intelligence Platform"
UNREACHABLE_EMAIL_DOMAINS = ("noreply", "no-reply", "example.com", "localhost")
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
QUARTERLY_FORMS = {"10-Q", "10-Q/A"}


class SecEdgarError(RuntimeError):
    """Raised when SEC EDGAR cannot supply usable company facts."""


# The first matching standard concept wins for a period. Older concepts remain
# as fallbacks because issuers can change taxonomy versions between filings.
SEC_CONCEPTS: dict[str, tuple[str, ...]] = {
    "total_revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
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
    counts: dict[str, int] = {}
    facts = payload.get("facts") or {}
    for taxonomy, mappings in _taxonomy_concepts(payload):
        taxonomy_facts = facts.get(taxonomy) or {}
        for metric in ("total_revenue", "total_assets", "net_income"):
            for concept in mappings.get(metric, ()):
                for unit, values in (taxonomy_facts.get(concept) or {}).get("units", {}).items():
                    if not _is_currency_unit(unit):
                        continue
                    count = sum(
                        1
                        for item in values
                        if str(item.get("form") or "") in ANNUAL_FORMS | QUARTERLY_FORMS
                    )
                    counts[unit] = counts.get(unit, 0) + count
    if not counts:
        return "USD"
    return max(counts, key=lambda unit: (counts[unit], unit == "USD"))


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
    if item.get("fp") not in {None, "", "FY"}:
        return False
    delay = _filing_delay_days(item)
    if delay is not None and not 0 <= delay <= 300:
        return False
    duration = _duration_days(item)
    if metric in FLOW_METRICS and (duration is None or not 300 <= duration <= 430):
        return False
    return bool(item.get("end"))


def _valid_quarter(item: dict[str, Any], metric: str) -> bool:
    if str(item.get("form") or "") not in QUARTERLY_FORMS:
        return False
    if str(item.get("fp") or "") not in {"Q1", "Q2", "Q3"}:
        return False
    delay = _filing_delay_days(item)
    if delay is not None and not 0 <= delay <= 180:
        return False
    duration = _duration_days(item)
    if metric in FLOW_METRICS and (duration is None or not 45 <= duration <= 310):
        return False
    return bool(item.get("end"))


def _fact_score(item: dict[str, Any], metric: str, *, annual: bool) -> tuple[int, str, str]:
    duration = _duration_days(item) or 0
    if annual or metric in CUMULATIVE_QUARTER_METRICS:
        duration_score = duration
    elif metric in FLOW_METRICS:
        duration_score = -abs(duration - 91)
    else:
        duration_score = 0
    return duration_score, str(item.get("filed") or ""), str(item.get("accn") or "")


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
    for metric in INTERNAL_METRICS:
        metrics.pop(metric, None)


def _extract_company_periods(
    payload: dict[str, Any],
    *,
    cik: str,
    currency: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    facts = payload.get("facts") or {}
    annual_buckets: dict[tuple[str, str], dict[str, Any]] = {}
    quarter_buckets: dict[tuple[str, str, str], dict[str, Any]] = {}

    for taxonomy, mappings in _taxonomy_concepts(payload):
        taxonomy_facts = facts.get(taxonomy) or {}
        for metric, concepts in mappings.items():
            annual_selected: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}
            quarter_selected: dict[tuple[str, str, str], tuple[int, dict[str, Any]]] = {}
            for concept_priority, concept in enumerate(concepts):
                values = _unit_values(taxonomy_facts.get(concept) or {}, metric, currency)
                for item in values:
                    if _valid_annual(item, metric):
                        key = (str(item.get("fy") or str(item.get("end"))[:4]), str(item.get("end")))
                        current = annual_selected.get(key)
                        if (
                            current is None
                            or concept_priority < current[0]
                            or (
                                concept_priority == current[0]
                                and _fact_score(item, metric, annual=True)
                                > _fact_score(current[1], metric, annual=True)
                            )
                        ):
                            annual_selected[key] = (concept_priority, item)
                    if _valid_quarter(item, metric):
                        key = (
                            str(item.get("fy") or str(item.get("end"))[:4]),
                            str(item.get("fp")),
                            str(item.get("end")),
                        )
                        current = quarter_selected.get(key)
                        if (
                            current is None
                            or concept_priority < current[0]
                            or (
                                concept_priority == current[0]
                                and _fact_score(item, metric, annual=False)
                                > _fact_score(current[1], metric, annual=False)
                            )
                        ):
                            quarter_selected[key] = (concept_priority, item)

            for key, (_, item) in annual_selected.items():
                bucket = annual_buckets.setdefault(key, _period_bucket(item, cik))
                if metric not in bucket["metrics"]:
                    _put_metric(bucket, metric, item, float(item["val"]), cik)
            for key, (_, item) in quarter_selected.items():
                bucket = quarter_buckets.setdefault(key, _period_bucket(item, cik, key[1]))
                if metric not in bucket["metrics"]:
                    _put_metric(bucket, metric, item, float(item["val"]), cik)

    strongest_annual: dict[str, dict[str, Any]] = {}
    for period in annual_buckets.values():
        key = period["period_end"]
        current = strongest_annual.get(key)
        score = (len(period["metrics"]), period["filed_at"], period["fiscal_year"])
        current_score = (
            len(current["metrics"]), current["filed_at"], current["fiscal_year"]
        ) if current else (-1, "", "")
        if score > current_score:
            strongest_annual[key] = period
    annual = sorted(strongest_annual.values(), key=lambda item: item["period_end"])
    quarters = sorted(
        quarter_buckets.values(),
        key=lambda item: (item["fiscal_year"], item["quarter"], item["period_end"]),
    )

    # Keep the strongest period when an issuer reports duplicate fiscal labels.
    strongest_quarters: dict[tuple[str, str], dict[str, Any]] = {}
    for period in quarters:
        key = (period["fiscal_year"], period["quarter"])
        current = strongest_quarters.get(key)
        score = (len(period["metrics"]), period["filed_at"], period["period_end"])
        current_score = (
            len(current["metrics"]), current["filed_at"], current["period_end"]
        ) if current else (-1, "", "")
        if score > current_score:
            strongest_quarters[key] = period
    quarters = sorted(
        strongest_quarters.values(),
        key=lambda item: (item["fiscal_year"], item["quarter"]),
    )

    # Cash-flow statements commonly report year-to-date values in Q2/Q3. Turn
    # them into discrete quarters only when the facts share the same start date.
    by_year: dict[str, dict[str, dict[str, Any]]] = {}
    for period in quarters:
        by_year.setdefault(period["fiscal_year"], {})[period["quarter"]] = period
    for periods in by_year.values():
        for metric in CUMULATIVE_QUARTER_METRICS:
            previous_raw: float | None = None
            previous_start: str | None = None
            for quarter in ("Q1", "Q2", "Q3"):
                period = periods.get(quarter)
                if not period or metric not in period["metrics"]:
                    continue
                meta = period["_metric_meta"].get(metric) or {}
                raw = float(meta.get("raw_value"))
                start = str(meta.get("start") or "")
                duration = int(meta.get("duration_days") or 0)
                if duration > 135 and previous_raw is not None and start == previous_start:
                    period["metrics"][metric] = raw - previous_raw
                previous_raw = raw
                previous_start = start

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
    return {
        "symbol": symbol,
        "cik": cik,
        "entity_name": str(payload.get("entityName") or symbol),
        "currency": currency,
        "annual": annual,
        "quarterly": quarterly,
        "source": "SEC EDGAR companyfacts (10-K/10-Q XBRL)",
        "source_url": f"https://www.sec.gov/edgar/browse/?CIK={int(cik)}",
    }


def fetch_sec_companyfacts(
    symbol: str,
    *,
    ticker_map: dict[str, dict[str, Any]],
    timeout: int = 30,
) -> dict[str, Any]:
    ticker = symbol.strip().upper().replace(".", "-")
    identity = ticker_map.get(ticker)
    if not identity:
        raise SecEdgarError(f"ไม่พบ CIK ของ {symbol} ในรายการ ticker ของ SEC")
    cik = str(identity["cik"]).zfill(10)
    try:
        payload = _download_json(SEC_COMPANYFACTS_URL.format(cik=cik), timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        raise SecEdgarError(f"ดึง SEC Company Facts ของ {symbol} ไม่สำเร็จ: {exc}") from exc
    return normalize_companyfacts(payload, symbol=symbol, cik=cik)
