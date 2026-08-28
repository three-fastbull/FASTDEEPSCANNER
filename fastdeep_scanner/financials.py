from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from .currency import currency_label, currency_name_th, trading_currency
from .data_io import load_universe_metadata
from .sec_edgar import fetch_sec_companyfacts, load_sec_ticker_map
from .yahoo_prices import load_universe


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DIR = ROOT / "data" / "financial_cache"
DEFAULT_UPDATE_STATUS = ROOT / "data" / "fastdeep_financial_update_status.json"
DEFAULT_SEC_UPDATE_STATUS = ROOT / "data" / "fastdeep_sec_update_status.json"
DEFAULT_COVERAGE_REPORT = ROOT / "data" / "fastdeep_financial_coverage.json"
DEFAULT_SEC_TICKER_CACHE = ROOT / "data" / "sec_company_tickers.json"
YAHOO_TIMESERIES_URL = "https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries"


class FinancialDataError(RuntimeError):
    """Raised when a provider cannot return usable financial statements."""


METRIC_LABELS: dict[str, str] = {
    "total_revenue": "รายได้รวม",
    "cost_of_revenue": "ต้นทุนขาย",
    "gross_profit": "กำไรขั้นต้น",
    "operating_income": "กำไรจากการดำเนินงาน",
    "pretax_income": "กำไรก่อนภาษี",
    "tax_provision": "ภาษีเงินได้",
    "net_income": "กำไรสุทธิ",
    "basic_eps": "กำไรต่อหุ้น (EPS)",
    "total_assets": "สินทรัพย์รวม",
    "current_assets": "สินทรัพย์หมุนเวียน",
    "total_liabilities": "หนี้สินรวม",
    "current_liabilities": "หนี้สินหมุนเวียน",
    "total_debt": "หนี้สินที่มีภาระดอกเบี้ย",
    "stockholders_equity": "ส่วนของผู้ถือหุ้น",
    "cash_and_equivalents": "เงินสดและรายการเทียบเท่าเงินสด",
    "operating_cash_flow": "กระแสเงินสดจากการดำเนินงาน",
    "capital_expenditure": "เงินลงทุน (Capex)",
    "free_cash_flow": "กระแสเงินสดอิสระ (FCF)",
}

FINANCIAL_SECTIONS = [
    {
        "title": "บัญชีทางการเงินที่สำคัญ",
        "metrics": [
            "total_assets",
            "total_liabilities",
            "stockholders_equity",
            "total_debt",
            "cash_and_equivalents",
        ],
    },
    {
        "title": "งบกำไรขาดทุน",
        "metrics": [
            "total_revenue",
            "gross_profit",
            "operating_income",
            "pretax_income",
            "net_income",
            "basic_eps",
        ],
    },
    {
        "title": "กระแสเงินสด",
        "metrics": [
            "operating_cash_flow",
            "capital_expenditure",
            "free_cash_flow",
        ],
    },
]

RATIO_LABELS = {
    "roe": "ROE (%)",
    "roa": "ROA (%)",
    "net_margin": "อัตรากำไรสุทธิ (%)",
    "gross_margin": "อัตรากำไรขั้นต้น (%)",
    "debt_to_equity": "หนี้สินต่อทุน (D/E)",
    "fcf_margin": "อัตรา FCF ต่อรายได้ (%)",
}

METRIC_TYPES = {
    "total_revenue": "TotalRevenue",
    "cost_of_revenue": "CostOfRevenue",
    "gross_profit": "GrossProfit",
    "operating_income": "OperatingIncome",
    "pretax_income": "PretaxIncome",
    "tax_provision": "TaxProvision",
    "net_income": "NetIncome",
    "basic_eps": "BasicEPS",
    "total_assets": "TotalAssets",
    "current_assets": "CurrentAssets",
    "total_liabilities": "TotalLiabilitiesNetMinorityInterest",
    "current_liabilities": "CurrentLiabilities",
    "total_debt": "TotalDebt",
    "stockholders_equity": "StockholdersEquity",
    "cash_and_equivalents": "CashCashEquivalentsAndShortTermInvestments",
    "operating_cash_flow": "OperatingCashFlow",
    "capital_expenditure": "CapitalExpenditure",
    "free_cash_flow": "FreeCashFlow",
}

# How each line has to be read on screen. Money lines are shown in millions of
# the reporting currency; EPS is per share in that same currency and must never
# be scaled the same way.
METRIC_UNITS: dict[str, str] = {
    "basic_eps": "per_share",
}

CORE_ANNUAL_METRICS = (
    "total_revenue",
    "net_income",
    "total_assets",
    "total_liabilities",
    "stockholders_equity",
)

FLOW_METRICS = {
    "total_revenue",
    "cost_of_revenue",
    "gross_profit",
    "operating_income",
    "pretax_income",
    "tax_provision",
    "net_income",
    "operating_cash_flow",
    "capital_expenditure",
    "free_cash_flow",
}


def _download_json(url: str, timeout: int = 25) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 FastDeepScanner/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _write_update_status(path: Path, state: str, **details: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps({"state": state, "updated_at": datetime.now(UTC).isoformat(), **details}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _financial_url(symbol: str) -> str:
    now = datetime.now(UTC)
    period_start = now - timedelta(days=365 * 7)
    types = [f"annual{value}" for value in METRIC_TYPES.values()]
    types.extend(f"quarterly{value}" for value in METRIC_TYPES.values())
    query = urllib.parse.urlencode(
        {
            "symbol": symbol,
            "type": ",".join(types),
            "period1": int(period_start.timestamp()),
            "period2": int(now.timestamp()),
        }
    )
    return f"{YAHOO_TIMESERIES_URL}/{urllib.parse.quote(symbol, safe='')}?{query}"


def _safe_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_periods(payload: dict[str, Any], prefix: str) -> tuple[list[dict[str, Any]], str]:
    reverse_types = {f"{prefix}{provider_name}": metric for metric, provider_name in METRIC_TYPES.items()}
    buckets: dict[str, dict[str, Any]] = {}
    currency = ""
    results = payload.get("timeseries", {}).get("result") or []

    for result in results:
        for provider_key, metric in reverse_types.items():
            for item in result.get(provider_key) or []:
                period_end = str(item.get("asOfDate") or "")
                if not period_end:
                    continue
                raw = _safe_number((item.get("reportedValue") or {}).get("raw"))
                if raw is None:
                    continue
                bucket = buckets.setdefault(period_end, {"period_end": period_end, "metrics": {}})
                bucket["metrics"][metric] = raw
                currency = currency or str(item.get("currencyCode") or "")

    periods = sorted(buckets.values(), key=lambda item: item["period_end"])
    return periods, currency


def _value(metrics: dict[str, Any], key: str) -> float | None:
    return _safe_number(metrics.get(key))


def _ratio(numerator: float | None, denominator: float | None, multiplier: float = 100.0) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    return numerator / denominator * multiplier


# ส่วนของผู้ถือหุ้นที่ติดลบหรือเล็กจนแทบเป็นศูนย์ทำให้ ROE และ D/E ระเบิด
# บริษัทที่ซื้อหุ้นคืนหนักจนทุนติดลบเคยได้ ROE 15,367% และ D/E -18 ซึ่งจะผ่าน
# เกณฑ์คุณภาพทั้งที่ควรตก จึงไม่ประกาศอัตราส่วนกลุ่มนี้เมื่อฐานไม่มีความหมาย
MINIMUM_EQUITY_TO_ASSETS = 0.01


def _equity_base_is_usable(equity: float | None, assets: float | None) -> bool:
    if equity is None or equity <= 0:
        return False
    if assets and equity / assets < MINIMUM_EQUITY_TO_ASSETS:
        return False
    return True


def _add_ratios(periods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, period in enumerate(periods):
        metrics = period["metrics"]
        previous = periods[index - 1]["metrics"] if index else {}
        equity = _value(metrics, "stockholders_equity")
        assets = _value(metrics, "total_assets")
        prior_equity = _value(previous, "stockholders_equity")
        prior_assets = _value(previous, "total_assets")
        average_equity = (equity + prior_equity) / 2 if equity is not None and prior_equity is not None else equity
        average_assets = (assets + prior_assets) / 2 if assets is not None and prior_assets is not None else assets
        revenue = _value(metrics, "total_revenue")
        net_income = _value(metrics, "net_income")
        gross_profit = _value(metrics, "gross_profit")
        total_debt = _value(metrics, "total_debt")
        free_cash_flow = _value(metrics, "free_cash_flow")

        roe_usable = _equity_base_is_usable(average_equity, average_assets)
        de_usable = _equity_base_is_usable(equity, assets)
        notes: dict[str, str] = {}
        if not roe_usable and average_equity is not None:
            notes["roe"] = (
                "ส่วนของผู้ถือหุ้นติดลบหรือเล็กเกินกว่าจะใช้เป็นฐานคำนวณ ROE ได้อย่างมีความหมาย"
            )
        if not de_usable and equity is not None:
            notes["debt_to_equity"] = (
                "ส่วนของผู้ถือหุ้นติดลบหรือเล็กเกินไป จึงไม่ประกาศอัตราหนี้สินต่อทุน"
            )

        output.append(
            {
                **period,
                "ratios": {
                    "roe": _ratio(net_income, average_equity) if roe_usable else None,
                    "roa": _ratio(net_income, average_assets),
                    "net_margin": _ratio(net_income, revenue),
                    "gross_margin": _ratio(gross_profit, revenue),
                    "debt_to_equity": _ratio(total_debt, equity, multiplier=1.0) if de_usable else None,
                    "fcf_margin": _ratio(free_cash_flow, revenue),
                },
                "ratio_notes": notes,
                "negative_equity": equity is not None and equity <= 0,
            }
        )
    return output


def _quarter_name(period_end: str) -> str:
    try:
        month = int(period_end[5:7])
    except (TypeError, ValueError):
        return "Q?"
    return f"Q{((month - 1) // 3) + 1}"


def _quarterly_by_year(
    periods: list[dict[str, Any]], annual_periods: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for period in periods:
        year = str(period.get("fiscal_year") or period["period_end"][:4])
        quarter = str(period.get("quarter") or _quarter_name(period["period_end"]))
        grouped.setdefault(year, []).append({**period, "fiscal_year": year, "quarter": quarter})

    for year, values in grouped.items():
        values.sort(key=lambda item: item["period_end"])
        by_quarter = {item["quarter"]: item for item in values}
        grouped[year] = [by_quarter[key] for key in ("Q1", "Q2", "Q3", "Q4") if key in by_quarter]

    annual_by_year = {
        str(item.get("fiscal_year") or item["period_end"][:4]): item
        for item in annual_periods
    }
    for year, annual in annual_by_year.items():
        entries = grouped.setdefault(year, [])
        quarters = {entry["quarter"]: entry for entry in entries}
        if "Q4" not in quarters:
            q4_metrics: dict[str, float] = {}
            for metric, annual_value in annual["metrics"].items():
                annual_value = _safe_number(annual_value)
                # EPS uses period-specific weighted shares, not annual minus quarterly EPS.
                if annual_value is None or METRIC_UNITS.get(metric) == "per_share":
                    continue
                if metric in FLOW_METRICS:
                    prior_values = [
                        _value(quarters.get(quarter, {}).get("metrics", {}), metric)
                        for quarter in ("Q1", "Q2", "Q3")
                    ]
                    if all(value is not None for value in prior_values):
                        q4_metrics[metric] = annual_value - sum(value for value in prior_values if value is not None)
                else:
                    q4_metrics[metric] = annual_value
            if q4_metrics:
                entries.append(
                    {
                        "period_end": annual["period_end"],
                        "fiscal_year": year,
                        "quarter": "Q4",
                        "metrics": q4_metrics,
                        "derived_from_annual": True,
                        "source_form": annual.get("source_form"),
                        "accession": annual.get("accession"),
                        "filed_at": annual.get("filed_at"),
                        "source_url": annual.get("source_url"),
                    }
                )
                entries.sort(key=lambda item: item["quarter"])
    return {year: grouped[year] for year in sorted(grouped)}


def _growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous <= 0 or current < 0:
        return None
    return (current / previous - 1) * 100


def _cagr(current: float | None, first: float | None, years: int) -> float | None:
    if current is None or first is None or current <= 0 or first <= 0 or years <= 0:
        return None
    return ((current / first) ** (1 / years) - 1) * 100


def _difference(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return current - previous


def _vi_summary(periods: list[dict[str, Any]]) -> dict[str, Any]:
    if not periods:
        return {"available": False, "reason": "ยังไม่มีงบการเงินจากผู้ให้บริการ"}

    first = periods[0]
    latest = periods[-1]
    period_years = [int(period.get("fiscal_year") or period["period_end"][:4]) for period in periods]
    elapsed_years = period_years[-1] - period_years[0]
    latest_metrics = latest["metrics"]
    latest_ratios = latest["ratios"]
    first_ratios = first["ratios"] if elapsed_years > 0 else {}
    yearly = []
    for index, period in enumerate(periods):
        previous = periods[index - 1] if index and period_years[index] - period_years[index - 1] == 1 else None
        yearly.append(
            {
                "year": str(period.get("fiscal_year") or period["period_end"][:4]),
                "revenue_growth": _growth(
                    _value(period["metrics"], "total_revenue"),
                    _value(previous["metrics"], "total_revenue") if previous else None,
                ),
                "profit_growth": _growth(
                    _value(period["metrics"], "net_income"),
                    _value(previous["metrics"], "net_income") if previous else None,
                ),
                "net_margin": period["ratios"].get("net_margin"),
                "roe": period["ratios"].get("roe"),
                "debt_to_equity": period["ratios"].get("debt_to_equity"),
            }
        )

    checks = [
        {
            "key": "revenue",
            "label": "รายได้รวม",
            "value": _value(latest_metrics, "total_revenue"),
            "cagr": _cagr(
                _value(latest_metrics, "total_revenue"),
                _value(first["metrics"], "total_revenue"),
                elapsed_years,
            ),
        },
        {
            "key": "net_income",
            "label": "กำไรสุทธิ",
            "value": _value(latest_metrics, "net_income"),
            "cagr": _cagr(
                _value(latest_metrics, "net_income"),
                _value(first["metrics"], "net_income"),
                elapsed_years,
            ),
        },
        {
            "key": "net_margin",
            "label": "อัตรากำไรสุทธิ",
            "value": latest_ratios.get("net_margin"),
            "change": _difference(
                latest_ratios.get("net_margin"), first_ratios.get("net_margin"),
            ),
            "change_unit": "percentage_points",
        },
        {
            "key": "roe",
            "label": "ROE",
            "value": latest_ratios.get("roe"),
            "change": _difference(latest_ratios.get("roe"), first_ratios.get("roe")),
            "change_unit": "percentage_points",
        },
        {
            "key": "debt_to_equity",
            "label": "หนี้สินต่อทุน",
            "value": latest_ratios.get("debt_to_equity"),
            "change": _difference(
                latest_ratios.get("debt_to_equity"), first_ratios.get("debt_to_equity"),
            ),
            "change_unit": "multiple",
        },
        {
            "key": "free_cash_flow",
            "label": "กระแสเงินสดอิสระ",
            "value": _value(latest_metrics, "free_cash_flow"),
            "cagr": _cagr(
                _value(latest_metrics, "free_cash_flow"),
                _value(first["metrics"], "free_cash_flow"),
                elapsed_years,
            ),
        },
    ]
    return {
        "available": True,
        "period": (
            f"{first.get('fiscal_year') or first['period_end'][:4]}-"
            f"{latest.get('fiscal_year') or latest['period_end'][:4]}"
        ),
        "elapsed_years": elapsed_years,
        "yearly": yearly,
        "checks": checks,
        "latest": {
            "year": str(latest.get("fiscal_year") or latest["period_end"][:4]),
            "revenue": _value(latest_metrics, "total_revenue"),
            "net_income": _value(latest_metrics, "net_income"),
            "free_cash_flow": _value(latest_metrics, "free_cash_flow"),
            "roe": latest_ratios.get("roe"),
            "roa": latest_ratios.get("roa"),
            "net_margin": latest_ratios.get("net_margin"),
            "debt_to_equity": latest_ratios.get("debt_to_equity"),
        },
    }


def _cache_path(symbol: str, cache_dir: Path) -> Path:
    safe_symbol = symbol.replace("/", "_").replace("\\", "_").replace(".", "_")
    return cache_dir / f"{safe_symbol}.json"


def _read_cache(path: Path, max_age_hours: int) -> dict[str, Any] | None:
    if not path.exists():
        return None
    age_seconds = time.time() - path.stat().st_mtime
    if age_seconds > max_age_hours * 3600:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _with_currency_presentation(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach the unit labels every number on screen is read against.

    Applied on cache reads too, so statements saved before these fields existed
    still display a currency instead of a bare number.
    """
    symbol = str(payload.get("symbol") or "")
    currency = str(payload.get("currency") or "").upper()
    source = "provider"
    if not currency:
        # Yahoo omits the currency on some listings. Falling back to the
        # exchange is better than showing revenue with no unit at all.
        currency = trading_currency(symbol, str(payload.get("market") or ""))
        source = "exchange_default"
    payload["currency"] = currency
    payload["currency_name"] = currency_name_th(currency)
    payload["currency_label"] = currency_label(currency)
    payload.setdefault("currency_source", source)
    payload["currency_note"] = (
        f"ตัวเลขทุกบรรทัดเป็นสกุล {currency_label(currency)} ตามที่บริษัทยื่นงบ "
        "ระบบไม่แปลงค่าเงินให้ จึงห้ามนำไปเทียบตรง ๆ กับบริษัทที่ยื่นงบคนละสกุล"
    )
    payload["unit"] = "ล้าน"
    payload["unit_scale"] = 1_000_000
    payload["unit_label"] = f"ล้าน {currency}"
    payload["per_share_unit"] = f"{currency} ต่อหุ้น"
    payload["metric_units"] = METRIC_UNITS
    payload["vi_summary"] = _vi_summary(payload.get("annual") or [])
    for periods in (payload.get("quarterly_by_year") or {}).values():
        for period in periods:
            if period.get("derived_from_annual"):
                period["metrics"] = {
                    metric: value for metric, value in period.get("metrics", {}).items()
                    if METRIC_UNITS.get(metric) != "per_share"
                }
    return payload


def assess_financial_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Measure statement coverage without treating a cache file as complete data."""
    payload = payload or {}
    annual = sorted(payload.get("annual") or [], key=lambda item: str(item.get("period_end") or ""))
    annual = [item for item in annual if item.get("period_end")]
    annual_five = annual[-5:]
    annual_years = [
        str(item.get("fiscal_year") or str(item["period_end"])[:4])
        for item in annual_five
    ]

    metric_slots = len(annual_five) * len(CORE_ANNUAL_METRICS)
    metric_values = sum(
        1
        for period in annual_five
        for metric in CORE_ANNUAL_METRICS
        if _safe_number((period.get("metrics") or {}).get(metric)) is not None
    )
    metric_coverage = metric_values / metric_slots * 100 if metric_slots else 0.0

    quarterly_by_year = payload.get("quarterly_by_year") or {}
    quarter_periods = 0
    full_quarter_years: list[str] = []
    quarter_metric_values = 0
    quarter_metric_slots = 0
    for year, periods in quarterly_by_year.items():
        period_list = list(periods or [])
        quarters = {str(item.get("quarter") or "") for item in period_list}
        quarter_periods += len(quarters & {"Q1", "Q2", "Q3", "Q4"})
        relevant_periods = [
            item for item in period_list if str(item.get("quarter") or "") in {"Q1", "Q2", "Q3", "Q4"}
        ]
        year_slots = len(relevant_periods) * len(CORE_ANNUAL_METRICS)
        year_values = sum(
            1
            for period in relevant_periods
            for metric in CORE_ANNUAL_METRICS
            if _safe_number((period.get("metrics") or {}).get(metric)) is not None
        )
        quarter_metric_slots += year_slots
        quarter_metric_values += year_values
        year_coverage = year_values / year_slots * 100 if year_slots else 0.0
        if {"Q1", "Q2", "Q3", "Q4"}.issubset(quarters) and year_coverage >= 80.0:
            full_quarter_years.append(str(year))

    quarter_metric_coverage = (
        quarter_metric_values / quarter_metric_slots * 100 if quarter_metric_slots else 0.0
    )

    annual_complete = len(annual_five) >= 5 and metric_coverage >= 80.0
    quarterly_complete = len(set(annual_years) & set(full_quarter_years)) >= 5
    if annual_complete and quarterly_complete:
        status = "complete"
        label = "ครบ 5 ปีและ Q1-Q4"
    elif annual_complete:
        status = "annual_complete"
        label = "รายปีครบ 5 ปี แต่ไตรมาสยังไม่ครบ"
    elif annual:
        status = "partial"
        label = "ข้อมูลงบบางส่วน"
    else:
        status = "missing"
        label = "ยังไม่มีข้อมูลงบ"

    gaps: list[str] = []
    if len(annual_five) < 5:
        gaps.append(f"ขาดงบรายปี {5 - len(annual_five)} งวด")
    if metric_coverage < 80.0:
        gaps.append(f"หัวข้อหลักครบ {metric_coverage:.0f}%")
    missing_quarter_years = [year for year in annual_years if year not in full_quarter_years]
    if missing_quarter_years:
        gaps.append(f"Q1-Q4 ไม่ครบ {len(missing_quarter_years)} ปี")

    return {
        "status": status,
        "status_label": label,
        "annual_periods": len(annual_five),
        "annual_target": 5,
        "annual_years": annual_years,
        "annual_complete": annual_complete,
        "core_metric_coverage_pct": round(metric_coverage, 1),
        "quarter_periods": quarter_periods,
        "quarter_core_metric_coverage_pct": round(quarter_metric_coverage, 1),
        "full_quarter_years": sorted(full_quarter_years),
        "quarterly_target_years": 5,
        "quarterly_complete": quarterly_complete,
        "latest_period": str(annual_five[-1]["period_end"]) if annual_five else None,
        "gaps": gaps,
    }


def audit_financial_cache(
    universe_path: str | Path,
    *,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    output_path: str | Path = DEFAULT_COVERAGE_REPORT,
) -> dict[str, Any]:
    metadata = load_universe_metadata(universe_path)
    cache_dir = Path(cache_dir)
    items: list[dict[str, Any]] = []
    by_market: dict[str, dict[str, int]] = {}
    by_source: dict[str, int] = {}

    for symbol, details in metadata.items():
        path = _cache_path(symbol, cache_dir)
        payload: dict[str, Any] | None = None
        error = ""
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                error = str(exc)
        quality = assess_financial_payload(payload)
        market = str(details.get("market") or payload and payload.get("market") or "Unknown")
        source_name = str((payload or {}).get("source") or "missing")
        if source_name.startswith("SEC EDGAR"):
            source_key = "SEC EDGAR"
        elif source_name.startswith("Yahoo Finance"):
            source_key = "Yahoo Finance"
        else:
            source_key = source_name
        by_source[source_key] = by_source.get(source_key, 0) + 1
        market_counts = by_market.setdefault(
            market,
            {"symbols": 0, "cached": 0, "annual_5y": 0, "complete": 0, "partial": 0, "missing": 0},
        )
        market_counts["symbols"] += 1
        if payload:
            market_counts["cached"] += 1
        if quality["annual_complete"]:
            market_counts["annual_5y"] += 1
        if quality["status"] == "complete":
            market_counts["complete"] += 1
        elif quality["status"] in {"annual_complete", "partial"}:
            market_counts["partial"] += 1
        else:
            market_counts["missing"] += 1
        items.append(
            {
                "symbol": symbol,
                "name": details.get("name") or symbol,
                "market": market,
                "source": (payload or {}).get("source"),
                "fetched_at": (payload or {}).get("fetched_at"),
                "cache_error": error or None,
                **quality,
            }
        )

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "symbols_requested": len(items),
        "cached_symbols": sum(item["status"] != "missing" for item in items),
        "annual_5y_symbols": sum(bool(item["annual_complete"]) for item in items),
        "complete_symbols": sum(item["status"] == "complete" for item in items),
        "partial_symbols": sum(item["status"] in {"annual_complete", "partial"} for item in items),
        "missing_symbols": sum(item["status"] == "missing" for item in items),
        "by_market": by_market,
        "by_source": by_source,
        "items": items,
    }
    report["cached_coverage_pct"] = round(
        report["cached_symbols"] / len(items) * 100, 1
    ) if items else 0.0
    report["annual_5y_coverage_pct"] = round(
        report["annual_5y_symbols"] / len(items) * 100, 1
    ) if items else 0.0
    report["complete_coverage_pct"] = round(
        report["complete_symbols"] / len(items) * 100, 1
    ) if items else 0.0
    _write_json_atomic(Path(output_path), report)
    return report


def _build_financial_payload(
    symbol: str,
    *,
    annual_periods: list[dict[str, Any]],
    quarterly_periods: list[dict[str, Any]],
    currency: str,
    source: str,
    source_url: str = "",
    provider_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = load_universe_metadata().get(symbol, {})
    annual = _add_ratios(
        sorted(annual_periods, key=lambda item: str(item.get("period_end") or ""))[-5:]
    )
    if not annual:
        raise FinancialDataError(f"ไม่พบงบการเงินของ {symbol} จาก {source}")
    annual_years = {
        str(item.get("fiscal_year") or str(item.get("period_end") or "")[:4])
        for item in annual
    }
    quarterly_by_year = {
        year: periods
        for year, periods in _quarterly_by_year(quarterly_periods, annual).items()
        if year in annual_years
    }
    output = {
        "symbol": symbol,
        "name": metadata.get("name") or symbol,
        "market": metadata.get("market") or "Unknown",
        "sector": metadata.get("sector") or "Unknown",
        "currency": currency.upper(),
        "unit": "ล้าน",
        "source": source,
        "source_url": source_url,
        "fetched_at": datetime.now(UTC).isoformat(),
        "cache_status": "fresh",
        "annual": annual,
        "quarterly_by_year": quarterly_by_year,
        "sections": FINANCIAL_SECTIONS,
        "metric_labels": METRIC_LABELS,
        "ratio_labels": RATIO_LABELS,
        "vi_summary": _vi_summary(annual),
        **(provider_metadata or {}),
    }
    output["data_quality"] = assess_financial_payload(output)
    return _with_currency_presentation(output)


def _sec_financial_payload(
    symbol: str,
    *,
    ticker_map: dict[str, dict[str, Any]] | None = None,
    request_timeout: int = 30,
) -> dict[str, Any]:
    if ticker_map is None:
        ticker_map = load_sec_ticker_map(
            DEFAULT_SEC_TICKER_CACHE,
            timeout=request_timeout,
        )
    normalized = fetch_sec_companyfacts(
        symbol,
        ticker_map=ticker_map,
        timeout=request_timeout,
    )
    return _build_financial_payload(
        symbol,
        annual_periods=normalized["annual"],
        quarterly_periods=normalized["quarterly"],
        currency=normalized["currency"],
        source=normalized["source"],
        source_url=normalized["source_url"],
        provider_metadata={
            "cik": normalized["cik"],
            "sec_entity_name": normalized["entity_name"],
        },
    )


def fetch_financials(
    symbol: str,
    *,
    refresh: bool = False,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    max_age_hours: int = 24,
    request_timeout: int = 20,
    provider: str = "auto",
    sec_ticker_map: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    if not symbol:
        raise FinancialDataError("กรุณาระบุชื่อย่อหุ้น")

    cache_dir = Path(cache_dir)
    cache_file = _cache_path(symbol, cache_dir)
    if not refresh:
        cached = _read_cache(cache_file, max_age_hours)
        if cached:
            cached["cache_status"] = "cached"
            cached["data_quality"] = assess_financial_payload(cached)
            return _with_currency_presentation(cached)

    provider = provider.strip().lower()
    if provider not in {"auto", "sec", "yahoo"}:
        raise FinancialDataError(f"ไม่รู้จักผู้ให้บริการงบ: {provider}")
    metadata = load_universe_metadata().get(symbol, {})
    market = metadata.get("market") or "Unknown"
    sec_error = ""
    if provider == "sec" or (provider == "auto" and market == "US"):
        try:
            output = _sec_financial_payload(
                symbol,
                ticker_map=sec_ticker_map,
                request_timeout=request_timeout,
            )
            _write_json_atomic(cache_file, output)
            return output
        except Exception as exc:  # noqa: BLE001
            if provider == "sec":
                raise FinancialDataError(f"ดึงงบ SEC ของ {symbol} ไม่สำเร็จ: {exc}") from exc
            sec_error = str(exc)
            existing = _read_cache(cache_file, max_age_hours=24 * 365 * 20)
            if existing and str(existing.get("source") or "").startswith("SEC EDGAR"):
                existing["cache_status"] = "stale_verified"
                existing["refresh_error"] = sec_error
                existing["data_quality"] = assess_financial_payload(existing)
                return _with_currency_presentation(existing)

    try:
        payload = _download_json(_financial_url(symbol), timeout=request_timeout)
    except Exception as exc:  # noqa: BLE001
        raise FinancialDataError(f"ดึงงบของ {symbol} ไม่สำเร็จ: {exc}") from exc

    annual, annual_currency = _extract_periods(payload, "annual")
    quarterly, quarterly_currency = _extract_periods(payload, "quarterly")
    output = _build_financial_payload(
        symbol,
        annual_periods=annual,
        quarterly_periods=quarterly,
        currency=annual_currency or quarterly_currency,
        source="Yahoo Finance fundamentals timeseries",
        provider_metadata={"provider_fallback_note": sec_error} if sec_error else None,
    )
    _write_json_atomic(cache_file, output)
    return output


def cache_universe_financials(
    universe_path: str | Path,
    *,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    pause_seconds: float = 0.75,
    refresh: bool = False,
    max_workers: int = 1,
    request_timeout: int = 20,
    cache_max_age_hours: int = 24 * 7,
    max_retries: int = 2,
    coverage_path: str | Path = DEFAULT_COVERAGE_REPORT,
    markets: tuple[str, ...] = (),
) -> dict[str, Any]:
    symbols = load_universe(universe_path)
    if markets:
        selected_markets = {market.strip().upper() for market in markets}
        if selected_markets - {"US", "TH", "CN", "HK"}:
            raise ValueError("Unknown financial update market")
        metadata = load_universe_metadata(universe_path)
        symbols = [symbol for symbol in symbols if metadata.get(symbol, {}).get("market") in selected_markets]
    cache_dir = Path(cache_dir)
    status_path = cache_dir.parent / DEFAULT_UPDATE_STATUS.name
    cached_before = [
        symbol
        for symbol in symbols
        if not refresh and _read_cache(_cache_path(symbol, cache_dir), cache_max_age_hours)
    ]
    cached_set = set(cached_before)
    pending = [symbol for symbol in symbols if symbol not in cached_set]
    succeeded: set[str] = set(cached_before)
    errors: dict[str, str] = {}
    _write_update_status(
        status_path,
        "running",
        symbols_requested=len(symbols),
        symbols_cached_before=len(cached_before),
        symbols_pending=len(pending),
        symbols_processed=len(cached_before),
        symbols_succeeded=len(succeeded),
        failed_count=0,
    )

    rate_lock = threading.Lock()
    next_request_at = [0.0]

    def wait_for_request_slot(multiplier: float = 1.0) -> None:
        interval = max(0.0, pause_seconds * multiplier)
        with rate_lock:
            now = time.monotonic()
            wait_seconds = max(0.0, next_request_at[0] - now)
            if wait_seconds:
                time.sleep(wait_seconds)
            next_request_at[0] = time.monotonic() + interval

    def cache_symbol(symbol: str) -> tuple[str, str | None]:
        wait_for_request_slot()
        try:
            output = fetch_financials(
                symbol,
                refresh=True,
                cache_dir=cache_dir,
                request_timeout=request_timeout,
                provider="auto",
            )
            if output.get("cache_status") == "stale_verified":
                return symbol, output.get("refresh_error") or "Kept previous verified SEC statements; refresh failed"
            return symbol, None
        except Exception as exc:  # noqa: BLE001
            return symbol, str(exc)

    try:
        attempt_symbols = pending
        for attempt in range(max(0, max_retries) + 1):
            if not attempt_symbols:
                break
            round_errors: dict[str, str] = {}
            completed_in_round = 0
            with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
                futures = [executor.submit(cache_symbol, symbol) for symbol in attempt_symbols]
                for future in as_completed(futures):
                    symbol, error = future.result()
                    completed_in_round += 1
                    if error:
                        round_errors[symbol] = error
                    else:
                        succeeded.add(symbol)
                        errors.pop(symbol, None)
                    processed = len(cached_before) + len(succeeded - cached_set) + len(round_errors)
                    if completed_in_round % 5 == 0 or completed_in_round == len(attempt_symbols):
                        _write_update_status(
                            status_path,
                            "running",
                            symbols_requested=len(symbols),
                            symbols_cached_before=len(cached_before),
                            symbols_pending=len(pending),
                            symbols_processed=min(processed, len(symbols)),
                            symbols_succeeded=len(succeeded),
                            failed_count=len(round_errors),
                            retry_attempt=attempt,
                            last_symbol=symbol,
                        )
            errors = round_errors
            attempt_symbols = list(round_errors)
            if attempt_symbols and attempt < max_retries:
                time.sleep(max(1.0, pause_seconds * (attempt + 2) * 4))

        coverage = audit_financial_cache(
            universe_path,
            cache_dir=cache_dir,
            output_path=coverage_path,
        )
        failed = [f"{symbol}: {message}" for symbol, message in sorted(errors.items())]
        final_state = "complete" if not failed else "partial"
        _write_update_status(
            status_path,
            final_state,
            symbols_requested=len(symbols),
            symbols_succeeded=len(succeeded),
            failed_count=len(failed),
            symbols_cached=coverage["cached_symbols"],
            annual_5y_symbols=coverage["annual_5y_symbols"],
            complete_symbols=coverage["complete_symbols"],
            missing_symbols=coverage["missing_symbols"],
            failed=failed[:100],
        )
        return {
            "symbols": len(symbols),
            "succeeded": sorted(succeeded),
            "failed": failed,
            "coverage": coverage,
        }
    except Exception as exc:
        _write_update_status(status_path, "failed", symbols_requested=len(symbols), error=str(exc))
        raise


def cache_sec_universe_financials(
    universe_path: str | Path,
    *,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    groups: tuple[str, ...] = ("SP500", "NASDAQ100", "SP400"),
    symbols: tuple[str, ...] = (),
    pause_seconds: float = 0.20,
    refresh: bool = False,
    request_timeout: int = 30,
    cache_max_age_hours: int = 24 * 7,
    max_retries: int = 2,
    limit: int | None = None,
    coverage_path: str | Path = DEFAULT_COVERAGE_REPORT,
    ticker_cache_path: str | Path = DEFAULT_SEC_TICKER_CACHE,
) -> dict[str, Any]:
    metadata = load_universe_metadata(universe_path)
    group_filter = {group.strip().upper() for group in groups if group.strip()}
    symbol_filter = {symbol.strip().upper() for symbol in symbols if symbol.strip()}
    selected = []
    for symbol, details in metadata.items():
        index_groups = {
            group.strip().upper()
            for group in str(details.get("index_groups") or "").split("|")
            if group.strip()
        }
        if str(details.get("market") or "").upper() != "US":
            continue
        if symbol_filter and symbol not in symbol_filter:
            continue
        if not symbol_filter and group_filter and not index_groups & group_filter:
            continue
        selected.append(symbol)
    if limit is not None:
        selected = selected[: max(0, limit)]

    cache_dir = Path(cache_dir)
    status_path = cache_dir.parent / DEFAULT_SEC_UPDATE_STATUS.name
    cached_before: list[str] = []
    for symbol in selected:
        cached = None if refresh else _read_cache(
            _cache_path(symbol, cache_dir), cache_max_age_hours
        )
        if cached and str(cached.get("source") or "").startswith("SEC EDGAR"):
            cached_before.append(symbol)
    cached_set = set(cached_before)
    pending = [symbol for symbol in selected if symbol not in cached_set]
    succeeded = set(cached_before)
    errors: dict[str, str] = {}
    _write_update_status(
        status_path,
        "running",
        provider="SEC EDGAR",
        symbols_requested=len(selected),
        symbols_cached_before=len(cached_before),
        symbols_pending=len(pending),
        symbols_processed=len(cached_before),
        symbols_succeeded=len(succeeded),
        failed_count=0,
    )

    next_request_at = 0.0

    def wait_for_request_slot() -> None:
        nonlocal next_request_at
        wait_seconds = max(0.0, next_request_at - time.monotonic())
        if wait_seconds:
            time.sleep(wait_seconds)
        next_request_at = time.monotonic() + max(0.11, pause_seconds)

    try:
        ticker_map = (
            load_sec_ticker_map(ticker_cache_path, timeout=request_timeout)
            if pending
            else {}
        )
        attempt_symbols = pending
        for attempt in range(max(0, max_retries) + 1):
            if not attempt_symbols:
                break
            round_errors: dict[str, str] = {}
            for index, symbol in enumerate(attempt_symbols, start=1):
                wait_for_request_slot()
                try:
                    output = _sec_financial_payload(
                        symbol,
                        ticker_map=ticker_map,
                        request_timeout=request_timeout,
                    )
                    _write_json_atomic(_cache_path(symbol, cache_dir), output)
                    succeeded.add(symbol)
                except Exception as exc:  # noqa: BLE001
                    round_errors[symbol] = str(exc)
                if index % 5 == 0 or index == len(attempt_symbols):
                    processed = len(cached_before) + len(succeeded - cached_set) + len(round_errors)
                    _write_update_status(
                        status_path,
                        "running",
                        provider="SEC EDGAR",
                        symbols_requested=len(selected),
                        symbols_cached_before=len(cached_before),
                        symbols_pending=len(pending),
                        symbols_processed=min(processed, len(selected)),
                        symbols_succeeded=len(succeeded),
                        failed_count=len(round_errors),
                        retry_attempt=attempt,
                        last_symbol=symbol,
                    )
            errors = round_errors
            attempt_symbols = list(round_errors)
            if attempt_symbols and attempt < max_retries:
                time.sleep(max(1.0, pause_seconds * (attempt + 2) * 10))

        coverage = audit_financial_cache(
            universe_path,
            cache_dir=cache_dir,
            output_path=coverage_path,
        )
        failed = [f"{symbol}: {message}" for symbol, message in sorted(errors.items())]
        final_state = "complete" if not failed else "partial"
        _write_update_status(
            status_path,
            final_state,
            provider="SEC EDGAR",
            symbols_requested=len(selected),
            symbols_succeeded=len(succeeded),
            failed_count=len(failed),
            symbols_cached=coverage["cached_symbols"],
            annual_5y_symbols=coverage["annual_5y_symbols"],
            complete_symbols=coverage["complete_symbols"],
            missing_symbols=coverage["missing_symbols"],
            failed=failed[:100],
        )
        return {
            "symbols": len(selected),
            "succeeded": sorted(succeeded),
            "failed": failed,
            "coverage": coverage,
        }
    except Exception as exc:
        _write_update_status(
            status_path,
            "failed",
            provider="SEC EDGAR",
            symbols_requested=len(selected),
            error=str(exc),
        )
        raise
