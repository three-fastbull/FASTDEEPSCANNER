from __future__ import annotations

import html
from datetime import UTC, datetime
from typing import Any

from .models import FundamentalSnapshot, ScanResult, StockCandle


def _sparkline_svg(candles: list[StockCandle], width: int = 760, height: int = 260) -> str:
    if not candles:
        return ""
    closes = [candle.close for candle in candles[-140:]]
    high = max(closes)
    low = min(closes)
    span = max(high - low, 0.0001)
    points: list[str] = []
    for idx, close in enumerate(closes):
        x = idx / max(1, len(closes) - 1) * width
        y = height - ((close - low) / span * (height - 24)) - 12
        points.append(f"{x:.2f},{y:.2f}")
    last = closes[-1]
    return f"""
    <svg viewBox="0 0 {width} {height}" role="img" aria-label="Price trend">
      <rect x="0" y="0" width="{width}" height="{height}" fill="#f7f9fc"/>
      <polyline fill="none" stroke="#2563eb" stroke-width="3" points="{' '.join(points)}"/>
      <line x1="0" x2="{width}" y1="{height - 38}" y2="{height - 38}" stroke="#d9e1ec"/>
      <text x="12" y="28" fill="#0f172a" font-size="18">{html.escape(candles[-1].symbol)} {last:.2f}</text>
    </svg>
    """


def _score_row(label: str, value: float) -> str:
    return f"<tr><th>{html.escape(label)}</th><td>{value:.1f}</td></tr>"


def build_report_html(
    result: ScanResult,
    candles: list[StockCandle],
    snapshot: FundamentalSnapshot,
    data_health: dict[str, Any] | None = None,
) -> str:
    patterns = "".join(
        f"<li><b>{html.escape(pattern.label)}</b>: {html.escape('; '.join(pattern.reasons))}</li>"
        for pattern in result.patterns
    )
    insights = "".join(
        f"<section><h3>{html.escape(insight.agent)}</h3><p>{html.escape(insight.summary)}</p>"
        f"<ul>{''.join(f'<li>{html.escape(item)}</li>' for item in insight.bullets)}</ul></section>"
        for insight in result.insights
    )
    warnings = "".join(f"<li>{html.escape(warning)}</li>" for warning in result.warnings)
    risk = result.risk_plan
    targets = ", ".join(f"{target:.2f}" for target in risk.targets)
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    data_health = data_health or {}
    health_message = data_health.get("message") or "Data health unavailable"
    health_class = "ready" if data_health.get("can_publish") else "warning"

    summary = result.decision_summary or {}
    verification = (
        "Verified financial statements"
        if snapshot.fundamentals_verified
        else "Pending - technical candidate only"
    )
    reporting_currency = result.reporting_currency or "unknown currency"
    valuation_line = (
        summary.get("valuation", {}).get("detail")
        if result.valuation_verified
        else summary.get("valuation", {}).get("detail") or "Valuation could not be derived"
    )
    business_line = (
        f"{snapshot.moat} / {snapshot.ai_trend}"
        if result.research_verified
        else "Not reviewed by an analyst yet"
    )
    evidence_line = (result.evidence or {}).get("label") or "No historical study available"
    return f"""<!doctype html>
<html lang="th">
<head>
  <meta charset="utf-8">
  <title>FastDeep Report - {html.escape(result.symbol)}</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; color: #0f172a; background: #fff; }}
    main {{ max-width: 920px; margin: 0 auto; padding: 32px; }}
    h1 {{ margin: 0 0 6px; font-size: 30px; }}
    h2 {{ margin-top: 28px; border-bottom: 1px solid #d9e1ec; padding-bottom: 8px; }}
    h3 {{ margin-bottom: 6px; }}
    .muted {{ color: #526173; }}
    .badge {{ display: inline-block; padding: 4px 9px; border-radius: 6px; background: #e7f0ff; color: #174ea6; font-weight: 700; }}
    .health {{ padding: 10px 12px; border-radius: 6px; font-weight: 700; }}
    .health.ready {{ background: #eaf8f0; color: #116638; }}
    .health.warning {{ background: #fff4df; color: #9a5b00; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 9px 10px; border-bottom: 1px solid #e6ebf2; }}
    th {{ color: #526173; width: 48%; }}
    section {{ page-break-inside: avoid; }}
    @media print {{ main {{ padding: 18mm; }} .no-print {{ display: none; }} }}
  </style>
</head>
<body>
  <main>
    <button class="no-print" onclick="window.print()">Save as PDF</button>
    <p class="muted">Generated {generated}</p>
    <p class="health {health_class}">Data Health: {html.escape(str(health_message))} | Latest candle: {html.escape(str(data_health.get('latest_candle_date') or '-'))}</p>
    <h1>{html.escape(result.symbol)} - {html.escape(result.name)}</h1>
    <p><span class="badge">{html.escape(result.grade)}</span> {html.escape(result.decision)} | {html.escape(result.market)} | {html.escape(result.sector)} | TF {html.escape(result.timeframe)}</p>
    {_sparkline_svg(candles)}

    <h2>Scanner Verdict</h2>
    <div class="grid">
      <table>
        {_score_row("Final score", result.final_score)}
        {_score_row("Technical", result.technical_score)}
        {_score_row("Financial", result.fundamental_score)}
        {_score_row("Business quality", result.business_score)}
        {_score_row("Valuation", result.valuation_score)}
      </table>
      <table>
        <tr><th>Entry</th><td>{risk.entry:.2f}</td></tr>
        <tr><th>Stop</th><td>{risk.stop:.2f}</td></tr>
        <tr><th>Targets</th><td>{html.escape(targets)}</td></tr>
        <tr><th>Reward/risk</th><td>{risk.reward_risk:.2f}R</td></tr>
        <tr><th>Bias</th><td>{html.escape(risk.bias)}</td></tr>
      </table>
    </div>

    <h2>Pattern Evidence</h2>
    <ul>{patterns}</ul>

    <h2>Fundamental Snapshot</h2>
    <table>
      <tr><th>Verification</th><td>{html.escape(verification)}</td></tr>
      <tr><th>Statement period</th><td>{html.escape(snapshot.as_of or '-')} ({html.escape(reporting_currency)})</td></tr>
      <tr><th>ROE / ROA</th><td>{snapshot.roe:.1f}% / {snapshot.roa:.1f}%</td></tr>
      <tr><th>Debt to equity</th><td>{snapshot.debt_to_equity:.2f}x</td></tr>
      <tr><th>Growth</th><td>Revenue {snapshot.revenue_growth:.1f}%, profit {snapshot.profit_growth:.1f}%</td></tr>
      <tr><th>Valuation</th><td>{html.escape(valuation_line)}</td></tr>
      <tr><th>Moat / AI trend</th><td>{html.escape(business_line)}</td></tr>
      <tr><th>Historical evidence</th><td>{html.escape(evidence_line)}</td></tr>
    </table>

    <h2>Agent Notes</h2>
    {insights}

    <h2>Risk Notes</h2>
    <p>{html.escape(risk.invalidation)}</p>
    <p>{html.escape(risk.sizing_note)}</p>
    <ul>{warnings}</ul>
    <p class="muted">Research workflow only. This report is not financial advice.</p>
  </main>
</body>
</html>"""
