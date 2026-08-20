from __future__ import annotations

import json
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
from .yahoo_prices import load_universe


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DIR = ROOT / "data" / "financial_cache"
DEFAULT_UPDATE_STATUS = ROOT / "data" / "fastdeep_financial_update_status.json"
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
        output.append(
            {
                **period,
                "ratios": {
                    "roe": _ratio(net_income, average_equity),
                    "roa": _ratio(net_income, average_assets),
                    "net_margin": _ratio(net_income, revenue),
                    "gross_margin": _ratio(gross_profit, revenue),
                    "debt_to_equity": _ratio(total_debt, equity, multiplier=1.0),
                    "fcf_margin": _ratio(free_cash_flow, revenue),
                },
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
        year = period["period_end"][:4]
        grouped.setdefault(year, []).append({**period, "quarter": _quarter_name(period["period_end"])})

    for year, values in grouped.items():
        values.sort(key=lambda item: item["period_end"])
        by_quarter = {item["quarter"]: item for item in values}
        grouped[year] = [by_quarter[key] for key in ("Q1", "Q2", "Q3", "Q4") if key in by_quarter]

    annual_by_year = {item["period_end"][:4]: item for item in annual_periods}
    for year, annual in annual_by_year.items():
        entries = grouped.setdefault(year, [])
        quarters = {entry["quarter"]: entry for entry in entries}
        if "Q4" not in quarters:
            q4_metrics: dict[str, float] = {}
            for metric, annual_value in annual["metrics"].items():
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
                        "quarter": "Q4",
                        "metrics": q4_metrics,
                        "derived_from_annual": True,
                    }
                )
                entries.sort(key=lambda item: item["quarter"])
    return {year: grouped[year] for year in sorted(grouped)}


def _growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in {None, 0}:
        return None
    return (current / previous - 1) * 100


def _cagr(current: float | None, first: float | None, years: int) -> float | None:
    if current is None or first is None or first <= 0 or years <= 0:
        return None
    return ((current / first) ** (1 / years) - 1) * 100


def _vi_summary(periods: list[dict[str, Any]]) -> dict[str, Any]:
    if not periods:
        return {"available": False, "reason": "ยังไม่มีงบการเงินจากผู้ให้บริการ"}

    first = periods[0]
    latest = periods[-1]
    elapsed_years = max(1, len(periods) - 1)
    latest_metrics = latest["metrics"]
    latest_ratios = latest["ratios"]
    yearly = []
    for index, period in enumerate(periods):
        previous = periods[index - 1] if index else None
        yearly.append(
            {
                "year": period["period_end"][:4],
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
            "change": _growth(
                latest_ratios.get("net_margin"), first["ratios"].get("net_margin"),
            ),
        },
        {
            "key": "roe",
            "label": "ROE",
            "value": latest_ratios.get("roe"),
            "change": _growth(latest_ratios.get("roe"), first["ratios"].get("roe")),
        },
        {
            "key": "debt_to_equity",
            "label": "หนี้สินต่อทุน",
            "value": latest_ratios.get("debt_to_equity"),
            "change": _growth(
                latest_ratios.get("debt_to_equity"), first["ratios"].get("debt_to_equity"),
            ),
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
        "period": f"{first['period_end'][:4]}-{latest['period_end'][:4]}",
        "elapsed_years": elapsed_years,
        "yearly": yearly,
        "checks": checks,
        "latest": {
            "year": latest["period_end"][:4],
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
    return payload


def fetch_financials(
    symbol: str,
    *,
    refresh: bool = False,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    max_age_hours: int = 24,
    request_timeout: int = 20,
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
            return _with_currency_presentation(cached)

    try:
        payload = _download_json(_financial_url(symbol), timeout=request_timeout)
    except Exception as exc:  # noqa: BLE001
        raise FinancialDataError(f"ดึงงบของ {symbol} ไม่สำเร็จ: {exc}") from exc

    annual, annual_currency = _extract_periods(payload, "annual")
    quarterly, quarterly_currency = _extract_periods(payload, "quarterly")
    annual = _add_ratios(annual[-5:])
    if not annual:
        raise FinancialDataError(f"ไม่พบงบการเงินของ {symbol} จาก Yahoo Finance")

    metadata = load_universe_metadata().get(symbol, {})
    market = metadata.get("market") or "Unknown"
    output = {
        "symbol": symbol,
        "name": metadata.get("name") or symbol,
        "market": market,
        "sector": metadata.get("sector") or "Unknown",
        "currency": (annual_currency or quarterly_currency or "").upper(),
        "unit": "ล้าน",
        "source": "Yahoo Finance fundamentals timeseries",
        "fetched_at": datetime.now(UTC).isoformat(),
        "cache_status": "fresh",
        "annual": annual,
        "quarterly_by_year": _quarterly_by_year(quarterly, annual),
        "sections": FINANCIAL_SECTIONS,
        "metric_labels": METRIC_LABELS,
        "ratio_labels": RATIO_LABELS,
        "vi_summary": _vi_summary(annual),
    }
    output = _with_currency_presentation(output)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def cache_universe_financials(
    universe_path: str | Path,
    *,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    pause_seconds: float = 0.35,
    refresh: bool = False,
    max_workers: int = 4,
    request_timeout: int = 8,
) -> dict[str, Any]:
    symbols = load_universe(universe_path)
    cache_dir = Path(cache_dir)
    status_path = cache_dir.parent / DEFAULT_UPDATE_STATUS.name
    succeeded: list[str] = []
    failed: list[str] = []
    _write_update_status(status_path, "running", symbols_requested=len(symbols))
    def cache_symbol(symbol: str) -> tuple[str, str | None]:
        try:
            fetch_financials(
                symbol,
                refresh=refresh,
                cache_dir=cache_dir,
                request_timeout=request_timeout,
            )
            return symbol, None
        except FinancialDataError as exc:
            return symbol, str(exc)

    try:
        completed = 0
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
            futures = [executor.submit(cache_symbol, symbol) for symbol in symbols]
            for future in as_completed(futures):
                symbol, error = future.result()
                completed += 1
                if error:
                    failed.append(f"{symbol}: {error}")
                else:
                    succeeded.append(symbol)
                if completed % 5 == 0 or completed == len(symbols):
                    _write_update_status(
                        status_path,
                        "running",
                        symbols_requested=len(symbols),
                        symbols_processed=completed,
                        symbols_succeeded=len(succeeded),
                        failed_count=len(failed),
                    )
                if pause_seconds:
                    time.sleep(pause_seconds)
        retry_symbols = [item.split(":", 1)[0] for item in failed]
        if retry_symbols:
            failed = []
            for symbol in retry_symbols:
                try:
                    fetch_financials(
                        symbol,
                        refresh=refresh,
                        cache_dir=cache_dir,
                        request_timeout=max(16, request_timeout),
                    )
                    succeeded.append(symbol)
                except FinancialDataError as exc:
                    failed.append(f"{symbol}: {exc}")
                time.sleep(max(0.2, pause_seconds))
        _write_update_status(
            status_path,
            "complete",
            symbols_requested=len(symbols),
            symbols_succeeded=len(succeeded),
            failed_count=len(failed),
        )
        return {"symbols": len(symbols), "succeeded": succeeded, "failed": failed}
    except Exception as exc:
        _write_update_status(status_path, "failed", symbols_requested=len(symbols), error=str(exc))
        raise
