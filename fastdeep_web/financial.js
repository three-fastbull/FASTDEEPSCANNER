(() => {
  const elements = {
    views: [...document.querySelectorAll(".app-view")],
    navTabs: [...document.querySelectorAll(".nav-tab")],
    symbolInput: document.getElementById("financialSymbolInput"),
    symbolOptions: document.getElementById("financialSymbolOptions"),
    loadButton: document.getElementById("financialLoadButton"),
    refreshButton: document.getElementById("financialRefreshButton"),
    status: document.getElementById("financialStatus"),
    title: document.getElementById("financialTitle"),
    subtitle: document.getElementById("financialSubtitle"),
    unit: document.getElementById("financialUnit"),
    kpis: document.getElementById("financialKpis"),
    source: document.getElementById("financialSource"),
    annualPanel: document.getElementById("annualFinancialPanel"),
    trendToggle: document.getElementById("financialTrendToggle"),
    annualHead: document.getElementById("annualFinancialHead"),
    annualBody: document.getElementById("annualFinancialBody"),
    quarterlyTitle: document.getElementById("quarterlyTitle"),
    quarterlySubtitle: document.getElementById("quarterlySubtitle"),
    quarterlyNote: document.getElementById("quarterlyPeriodNote"),
    quarterlyHead: document.getElementById("quarterlyFinancialHead"),
    quarterlyBody: document.getElementById("quarterlyFinancialBody"),
    quarterlyPanel: document.getElementById("quarterlyPanel"),
    quarterlyYear: document.getElementById("quarterlyYearSelect"),
    annualBack: document.getElementById("annualBackButton"),
    viTitle: document.getElementById("viTitle"),
    viSubtitle: document.getElementById("viSubtitle"),
    viScore: document.getElementById("viScore"),
    thesisProgress: document.getElementById("thesisProgress"),
    viChecks: document.getElementById("viChecks"),
    viYearlyBody: document.getElementById("viYearlyBody"),
    targetRevenueCagr: document.getElementById("targetRevenueCagr"),
    targetProfitCagr: document.getElementById("targetProfitCagr"),
    targetRoe: document.getElementById("targetRoe"),
    targetDebtEquity: document.getElementById("targetDebtEquity"),
  };

  if (!elements.symbolInput) return;

  const state = {
    financials: null,
    selectedYear: null,
    activeView: "scannerView",
    financialRequestId: 0,
  };

  const GOOD_WHEN_UP = new Set([
    "stockholders_equity", "cash_and_equivalents", "total_revenue", "gross_profit",
    "operating_income", "pretax_income", "net_income", "basic_eps",
    "operating_cash_flow", "free_cash_flow", "roe", "roa", "net_margin",
    "gross_margin", "fcf_margin",
  ]);
  const GOOD_WHEN_DOWN = new Set(["total_debt", "debt_to_equity"]);
  const PROFIT_LIKE = new Set([
    "gross_profit", "operating_income", "pretax_income", "net_income",
    "basic_eps", "operating_cash_flow", "free_cash_flow",
  ]);

  const amountFormatter = new Intl.NumberFormat("th-TH", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 1,
  });
  const preciseFormatter = new Intl.NumberFormat("th-TH", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function number(value, fractionDigits = 1) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
    return fractionDigits === 1 ? amountFormatter.format(Number(value)) : preciseFormatter.format(Number(value));
  }

  function isPerShare(metric) {
    const units = state.financials?.metric_units || {};
    return units[metric] === "per_share" || metric === "basic_eps";
  }

  function currencyCode() {
    return state.financials?.currency || "";
  }

  // Money lines are reported in millions of the filing currency; per-share
  // lines are already per share and must not be scaled the same way.
  function amount(value, metric) {
    if (value === null || value === undefined) return "-";
    if (isPerShare(metric)) return number(value, 2);
    const scale = state.financials?.unit_scale || 1_000_000;
    return number(Number(value) / scale);
  }

  function metricUnitLabel(metric) {
    const code = currencyCode();
    if (!code) return "";
    return isPerShare(metric) ? `${code} ต่อหุ้น` : `ล้าน ${code}`;
  }

  function percent(value) {
    return value === null || value === undefined ? "-" : `${number(value, 2)}%`;
  }

  function multiple(value) {
    return value === null || value === undefined ? "-" : `${number(value, 2)}x`;
  }

  function status(message, stateName = "") {
    elements.status.textContent = message;
    elements.status.dataset.state = stateName;
  }

  function normalizedSymbol() {
    return elements.symbolInput.value.trim().split(/[\s|]/)[0].toUpperCase();
  }

  function selectView(viewId) {
    state.activeView = viewId;
    for (const view of elements.views) view.classList.toggle("is-hidden", view.id !== viewId);
    for (const tab of elements.navTabs) {
      tab.classList.toggle("is-active", tab.dataset.viewTarget === viewId);
    }
    document.querySelector(".app-navigation").scrollIntoView({ block: "start" });
    const needsStatements = viewId === "financialsView" || viewId === "viView";
    if (needsStatements && state.financials?.symbol !== normalizedSymbol()) loadFinancials(false);
  }

  function selectScannerSymbol(symbol) {
    const nextSymbol = String(symbol || "").trim().toUpperCase();
    if (!nextSymbol) return;
    if (nextSymbol === normalizedSymbol() && state.financials?.symbol === nextSymbol) return;
    elements.symbolInput.value = nextSymbol;
    loadFinancials(false, nextSymbol);
  }

  async function loadUniverse() {
    try {
      const response = await fetch("/api/universe");
      const payload = await response.json();
      elements.symbolOptions.innerHTML = (payload.symbols || []).map((item) => (
        `<option value="${escapeHtml(item.symbol)}">${escapeHtml(item.name)} | ${escapeHtml(item.market)}</option>`
      )).join("");
    } catch {
      // Symbol input remains usable for a direct ticker when the index is unavailable.
    }
  }

  async function loadFinancials(refresh, requestedSymbol = "") {
    const symbol = String(requestedSymbol || normalizedSymbol()).trim().toUpperCase();
    if (!symbol) {
      status("กรุณาระบุชื่อย่อหุ้น เช่น AAPL หรือ DOHOME.BK", "error");
      return;
    }
    const requestId = ++state.financialRequestId;
    elements.loadButton.disabled = true;
    elements.refreshButton.disabled = true;
    status(refresh ? `กำลังดึงงบล่าสุดของ ${symbol}...` : `กำลังโหลดงบของ ${symbol}...`, "loading");
    try {
      const response = await fetch(`/api/financials?symbol=${encodeURIComponent(symbol)}&refresh=${refresh ? "1" : "0"}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "ไม่สามารถโหลดงบการเงินได้");
      if (requestId !== state.financialRequestId) return;
      state.financials = payload;
      state.selectedYear = fiscalYear(payload.annual.at(-1));
      renderFinancials();
      renderVi();
      if (window.fastDeepSelectedSymbol !== payload.symbol) {
        window.fastDeepSelectedSymbol = payload.symbol;
        window.dispatchEvent(new CustomEvent("fastdeep:symbol-selected", {
          detail: { symbol: payload.symbol, source: "financials" },
        }));
      }
      window.dispatchEvent(new CustomEvent("fastdeep:financials-verified", {
        detail: { symbol: payload.symbol },
      }));
      const quality = payload.data_quality || {};
      const qualityLabel = quality.status_label || "ยังไม่ได้ตรวจความครบถ้วน";
      const cacheLabel = payload.cache_status === "cached"
        ? "ใช้ข้อมูลที่บันทึกไว้"
        : (payload.cache_status === "stale_verified" ? "ใช้ SEC ล่าสุด เพราะอัปเดตใหม่ไม่ได้" : "อัปเดตแล้ว");
      status(
        `${payload.symbol}: ${qualityLabel} (${cacheLabel})${quality.gaps?.length ? ` — ${quality.gaps.join(" · ")}` : ""}`,
        quality.status === "complete" ? "ready" : "partial",
      );
    } catch (error) {
      if (requestId !== state.financialRequestId) return;
      status(error.message || "ไม่สามารถโหลดงบการเงินได้", "error");
    } finally {
      if (requestId !== state.financialRequestId) return;
      elements.loadButton.disabled = false;
      elements.refreshButton.disabled = false;
    }
  }

  function fiscalYear(period) {
    if (!period) return null;
    return String(period.fiscal_year || period.period_end?.slice(0, 4) || "") || null;
  }

  function changeTone(key, change) {
    if (Math.abs(change) < 0.000001) return "neutral";
    if (GOOD_WHEN_UP.has(key)) return change > 0 ? "ok" : "bad";
    if (GOOD_WHEN_DOWN.has(key)) return change < 0 ? "ok" : "bad";
    return "neutral";
  }

  function changeBadge(currentValue, previousValue, key, ratio = false) {
    if (currentValue === null || currentValue === undefined || previousValue === null || previousValue === undefined) return "";
    const current = Number(currentValue);
    const previous = Number(previousValue);
    if (!Number.isFinite(current) || !Number.isFinite(previous)) return "";
    if (PROFIT_LIKE.has(key) && previous <= 0) {
      if (current === previous) return '<small class="year-change" data-tone="neutral" title="ไม่เปลี่ยนแปลงจากปีก่อน">ทรงตัว</small>';
      if (previous < 0 && current > 0) return '<small class="year-change" data-tone="ok" title="พลิกจากขาดทุนเป็นกำไร">พลิกเป็นกำไร</small>';
      if (current === 0) return '<small class="year-change" data-tone="ok" title="จากขาดทุนมาเป็นศูนย์">ถึงจุดคุ้มทุน</small>';
      if (previous === 0 && current > 0) return '<small class="year-change" data-tone="ok" title="ปีก่อนเป็นศูนย์จึงไม่คำนวณเปอร์เซ็นต์">เริ่มเป็นบวก</small>';
      if (previous < 0 && current <= 0) {
        const improved = current > previous;
        return `<small class="year-change" data-tone="${improved ? "ok" : "bad"}" title="ยังขาดทุนเมื่อเทียบกับปีก่อน">${improved ? "ขาดทุนน้อยลง" : "ขาดทุนเพิ่ม"}</small>`;
      }
      return "";
    }
    if (PROFIT_LIKE.has(key) && previous >= 0 && current < 0) {
      return '<small class="year-change" data-tone="bad" title="พลิกจากกำไรเป็นขาดทุน">พลิกเป็นขาดทุน</small>';
    }
    if (!ratio && (previous <= 0 || current < 0)) return "";
    const change = ratio ? current - previous : (current / previous - 1) * 100;
    const unit = ratio ? (key === "debt_to_equity" ? "x" : " จุด") : "%";
    const precision = ratio ? 2 : 1;
    const threshold = ratio ? 0.01 : 0.1;
    const smallChange = change !== 0 && Math.abs(change) < threshold;
    const value = smallChange ? `<${threshold}` : `${change > 0 ? "+" : ""}${number(change, precision)}`;
    const arrow = change > 0 ? "▲" : change < 0 ? "▼" : "●";
    const direction = change > 0 ? "เพิ่มขึ้น" : change < 0 ? "ลดลง" : "ทรงตัว";
    const magnitude = smallChange ? `น้อยกว่า ${threshold}` : number(Math.abs(change), precision);
    return `<small class="year-change" data-tone="${changeTone(key, change)}" title="${direction}จากปีก่อน ${magnitude}${unit}">${arrow} ${escapeHtml(value)}${unit}</small>`;
  }

  function financialCell(period, metric, previousPeriod) {
    const year = fiscalYear(period);
    const value = period.metrics[metric];
    const previous = previousPeriod && year - fiscalYear(previousPeriod) === 1 ? previousPeriod.metrics?.[metric] : null;
    return `<td><button type="button" class="financial-period-button" data-year="${year}" title="ดู Q1-Q4 ปี ${year}">${amount(value, metric)}${changeBadge(value, previous, metric)}</button></td>`;
  }

  function ratioCell(period, key, previousPeriod) {
    const year = fiscalYear(period);
    const value = period.ratios[key];
    const formatted = key === "debt_to_equity" ? multiple(value) : percent(value);
    const previous = previousPeriod && year - fiscalYear(previousPeriod) === 1 ? previousPeriod.ratios?.[key] : null;
    return `<td><button type="button" class="financial-period-button" data-year="${year}" title="ดู Q1-Q4 ปี ${year}">${formatted}${changeBadge(value, previous, key, true)}</button></td>`;
  }

  function renderFinancials() {
    const data = state.financials;
    if (!data) return;
    const annual = data.annual || [];
    elements.title.textContent = `${data.symbol} - งบการเงินย้อนหลัง`;
    elements.subtitle.textContent = `${data.name} | ${data.market} | ${data.sector}`;
    elements.unit.textContent = data.unit_label || `${data.unit} ${data.currency || ""}`.trim();
    elements.unit.title = data.currency_note || "";
    const currencyOrigin = data.currency_source === "exchange_default"
      ? "สกุลเงินอนุมานจากตลาดที่จดทะเบียน เพราะผู้ให้บริการไม่ได้ระบุมาให้"
      : "สกุลเงินตามที่ผู้ให้บริการงบระบุ";
    const sourceText = `${data.source} | ${data.cache_status === "cached" ? "Cache ล่าสุด" : "อัปเดตล่าสุด"}: ${new Date(data.fetched_at).toLocaleString("th-TH")} | ${data.currency_label || ""} — ${currencyOrigin}`;
    elements.source.innerHTML = data.source_url
      ? `<a href="${escapeHtml(data.source_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(sourceText)}</a>`
      : escapeHtml(sourceText);

    const latest = annual.at(-1) || { metrics: {}, ratios: {} };
    const kpis = [
      ["รายได้ล่าสุด", amount(latest.metrics.total_revenue, "total_revenue"), metricUnitLabel("total_revenue")],
      ["กำไรสุทธิ", amount(latest.metrics.net_income, "net_income"), metricUnitLabel("net_income")],
      ["กำไรต่อหุ้น", amount(latest.metrics.basic_eps, "basic_eps"), metricUnitLabel("basic_eps")],
      ["ROE", percent(latest.ratios.roe), "ผลตอบแทนผู้ถือหุ้น"],
      ["D/E", multiple(latest.ratios.debt_to_equity), "หนี้สินต่อทุน"],
    ];
    elements.kpis.innerHTML = kpis.map(([label, value, note]) => (
      `<article class="financial-kpi"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note)}</small></article>`
    )).join("");

    elements.annualHead.innerHTML = `<tr><th scope="col">งวดงบการเงิน</th>${annual.map((period) => {
      const year = fiscalYear(period);
      return `<th scope="col"><button class="year-header-button ${year === state.selectedYear ? "is-selected" : ""}" type="button" data-year="${year}">${year}<small>${period.period_end}</small></button></th>`;
    }).join("")}</tr>`;

    const rows = [];
    rows.push(`<tr class="currency-banner-row"><th colspan="${annual.length + 1}">${escapeHtml(data.currency_note || "")}</th></tr>`);
    for (const section of data.sections || []) {
      rows.push(`<tr class="financial-section-row"><th colspan="${annual.length + 1}">${escapeHtml(section.title)}</th></tr>`);
      for (const metric of section.metrics) {
        rows.push(`<tr><th scope="row">${escapeHtml(data.metric_labels[metric] || metric)}<small>${escapeHtml(metricUnitLabel(metric))}</small></th>${annual.map((period, index) => financialCell(period, metric, annual[index - 1])).join("")}</tr>`);
      }
    }
    rows.push(`<tr class="financial-section-row"><th colspan="${annual.length + 1}">อัตราส่วนทางการเงินที่สำคัญ</th></tr>`);
    for (const [key, label] of Object.entries(data.ratio_labels || {})) {
      rows.push(`<tr><th scope="row">${escapeHtml(label)}</th>${annual.map((period, index) => ratioCell(period, key, annual[index - 1])).join("")}</tr>`);
    }
    elements.annualBody.innerHTML = rows.join("");
    renderQuarterly();
  }

  function renderQuarterly() {
    const data = state.financials;
    if (!data || !state.selectedYear) return;
    const periods = data.quarterly_by_year[state.selectedYear] || [];
    const byQuarter = new Map(periods.map((period) => [period.quarter, period]));
    const quarters = ["Q1", "Q2", "Q3", "Q4"];
    elements.quarterlyYear.innerHTML = (data.annual || []).map((period) => {
      const year = fiscalYear(period);
      return `<option value="${year}" ${String(year) === String(state.selectedYear) ? "selected" : ""}>${year}</option>`;
    }).join("");
    elements.quarterlyTitle.textContent = `${data.symbol} - รายไตรมาส ปี ${state.selectedYear} (${data.unit_label || ""})`;
    elements.quarterlySubtitle.textContent = "Q4*: รายได้และกำไรคำนวณจากทั้งปีลบ Q1-Q3 · งบดุลใช้ยอดสิ้นปี · EPS แสดงเฉพาะงวดที่มีรายงานตรง";
    elements.quarterlyNote.textContent = periods.length ? `${periods.length}/4 งวดจากผู้ให้บริการ` : "ไม่พบข้อมูลงวดรายไตรมาส";
    elements.quarterlyHead.innerHTML = `<tr><th>หัวข้องบการเงิน</th>${quarters.map((quarter) => {
      const period = byQuarter.get(quarter);
      const suffix = period?.derived_from_annual ? "*" : "";
      return `<th>${quarter}${suffix}<small>${period?.period_end || "-"}</small></th>`;
    }).join("")}</tr>`;
    const rows = [];
    for (const section of data.sections || []) {
      rows.push(`<tr class="financial-section-row"><th colspan="5">${escapeHtml(section.title)}</th></tr>`);
      for (const metric of section.metrics) {
        rows.push(`<tr><th scope="row">${escapeHtml(data.metric_labels[metric] || metric)}<small>${escapeHtml(metricUnitLabel(metric))}</small></th>${quarters.map((quarter) => {
          const period = byQuarter.get(quarter);
          return `<td>${period ? amount(period.metrics[metric], metric) : "-"}</td>`;
        }).join("")}</tr>`);
      }
    }
    elements.quarterlyBody.innerHTML = rows.join("");
  }

  function metricByKey(summary, key) {
    return (summary.checks || []).find((item) => item.key === key) || {};
  }

  function targetProgress(actual, target, options = {}) {
    if (!Number.isFinite(actual) || !Number.isFinite(target) || target <= 0) return null;
    if (options.inverse && actual <= 0) return actual === 0 ? 100 : 0;
    const raw = options.inverse ? target / actual * 100 : actual / target * 100;
    return Math.max(0, Math.min(100, raw));
  }

  function qualityLabel(value) {
    if (value === null) return "รอข้อมูล";
    if (value >= 100) return "ถึงหรือเกินเป้าหมาย";
    if (value >= 80) return "ใกล้เคียงเป้าหมาย";
    return "ยังตามเป้าไม่ทัน";
  }

  function progressCard(label, actual, target, progress, unit) {
    const safeProgress = progress === null ? 0 : progress;
    return `<article class="progress-card">
      <div><span>${escapeHtml(label)}</span><strong>${actual === null ? "-" : escapeHtml(actual)}${unit}</strong></div>
      <p>เป้าหมาย ${escapeHtml(target)}${unit} <b>${qualityLabel(progress)}</b></p>
      <div class="progress-track"><span style="width:${safeProgress}%"></span></div>
      <small>${progress === null ? "ข้อมูลหรือเป้าหมายไม่พร้อมประเมิน" : `เทียบเกณฑ์ ${number(progress, 0)}%`}</small>
    </article>`;
  }

  function renderVi() {
    const data = state.financials;
    if (!data?.vi_summary?.available) return;
    const summary = data.vi_summary;
    const revenueCheck = metricByKey(summary, "revenue");
    const profitCheck = metricByKey(summary, "net_income");
    const targets = {
      revenue: Number(elements.targetRevenueCagr.value),
      profit: Number(elements.targetProfitCagr.value),
      roe: Number(elements.targetRoe.value),
      debt: Number(elements.targetDebtEquity.value),
    };
    const revenueProgress = targetProgress(revenueCheck.cagr, targets.revenue);
    const profitProgress = targetProgress(profitCheck.cagr, targets.profit);
    const roeProgress = targetProgress(summary.latest.roe, targets.roe);
    const debtProgress = targetProgress(summary.latest.debt_to_equity, targets.debt, { inverse: true });
    const availableProgress = [revenueProgress, profitProgress, roeProgress, debtProgress].filter((value) => value !== null);
    const score = availableProgress.length === 4 ? Math.round(availableProgress.reduce((sum, value) => sum + value, 0) / 4) : null;

    elements.viTitle.textContent = `${data.symbol} - VI Thesis และ Financial Quality`;
    elements.viSubtitle.textContent = `${data.name} | งบ ${summary.period} | สกุลเงินของงบ ${data.currency_label || "-"} | เป้าหมายปรับได้จากข้อมูลของคุณ`;
    elements.viScore.textContent = score === null ? "-" : `${score}%`;
    elements.viScore.title = score === null
      ? `มีข้อมูลและเป้าหมายพร้อม ${availableProgress.length}/4 เกณฑ์`
      : "ค่าเฉลี่ยการถึงเกณฑ์ Thesis ทั้ง 4 ข้อ จำกัดแต่ละข้อที่ 100% ไม่ใช่โอกาสได้กำไร";
    elements.viScore.dataset.quality = score === null ? "pending" : score >= 100 ? "strong" : score >= 80 ? "watch" : "weak";
    elements.thesisProgress.innerHTML = [
      progressCard("Revenue CAGR", revenueCheck.cagr === null || revenueCheck.cagr === undefined ? null : number(revenueCheck.cagr, 1), targets.revenue, revenueProgress, "%"),
      progressCard("Net Profit CAGR", profitCheck.cagr === null || profitCheck.cagr === undefined ? null : number(profitCheck.cagr, 1), targets.profit, profitProgress, "%"),
      progressCard("ROE", summary.latest.roe === null || summary.latest.roe === undefined ? null : number(summary.latest.roe, 1), targets.roe, roeProgress, "%"),
      progressCard("D/E", summary.latest.debt_to_equity === null || summary.latest.debt_to_equity === undefined ? null : number(summary.latest.debt_to_equity, 2), targets.debt, debtProgress, "x"),
    ].join("");

    elements.viChecks.innerHTML = (summary.checks || []).map((check) => {
      const trend = check.cagr ?? check.change;
      const isDebt = check.key === "debt_to_equity";
      const displayValue = ["net_margin", "roe"].includes(check.key)
        ? percent(check.value)
        : isDebt
          ? multiple(check.value)
          : amount(check.value, check.key);
      const unit = ["net_margin", "roe", "debt_to_equity"].includes(check.key) ? "" : metricUnitLabel(check.key);
      const trendLabel = trend === null || trend === undefined
        ? "ข้อมูลไม่พอเทียบช่วงเวลา"
        : check.change_unit
          ? `${trend > 0 ? "+" : ""}${number(trend, 2)} ${check.change_unit === "percentage_points" ? "จุดเปอร์เซ็นต์" : "เท่า"} ตลอดช่วง`
          : `CAGR ${percent(trend)} ต่อปี`;
      return `<article class="vi-check">
        <span>${escapeHtml(check.label)}${unit ? ` <i>${escapeHtml(unit)}</i>` : ""}</span>
        <strong>${displayValue}</strong>
        <p>${trendLabel}</p>
      </article>`;
    }).join("");

    elements.viYearlyBody.innerHTML = (summary.yearly || []).map((row) => (`<tr>
      <th>${escapeHtml(row.year)}</th>
      <td>${percent(row.revenue_growth)}</td>
      <td>${percent(row.profit_growth)}</td>
      <td>${percent(row.net_margin)}</td>
      <td>${percent(row.roe)}</td>
      <td>${multiple(row.debt_to_equity)}</td>
    </tr>`)).join("");
  }

  elements.navTabs.forEach((tab) => tab.addEventListener("click", () => selectView(tab.dataset.viewTarget)));
  elements.loadButton.addEventListener("click", () => loadFinancials(false));
  elements.refreshButton.addEventListener("click", () => loadFinancials(true));
  elements.trendToggle.addEventListener("change", () => {
    elements.annualPanel.classList.toggle("hide-year-changes", !elements.trendToggle.checked);
  });
  window.addEventListener("fastdeep:symbol-selected", (event) => selectScannerSymbol(event.detail?.symbol));
  elements.symbolInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") loadFinancials(false);
  });
  elements.annualHead.addEventListener("click", (event) => {
    const button = event.target.closest("[data-year]");
    if (!button) return;
    state.selectedYear = button.dataset.year;
    renderFinancials();
    elements.quarterlyPanel.scrollIntoView({ block: "start" });
  });
  elements.annualBody.addEventListener("click", (event) => {
    const button = event.target.closest("[data-year]");
    if (!button) return;
    state.selectedYear = button.dataset.year;
    renderFinancials();
    elements.quarterlyPanel.scrollIntoView({ block: "start" });
  });
  elements.quarterlyYear.addEventListener("change", () => {
    state.selectedYear = elements.quarterlyYear.value;
    renderFinancials();
  });
  elements.annualBack.addEventListener("click", () => elements.annualPanel.scrollIntoView({ block: "start" }));
  [elements.targetRevenueCagr, elements.targetProfitCagr, elements.targetRoe, elements.targetDebtEquity]
    .forEach((input) => input.addEventListener("input", renderVi));

  if (window.fastDeepSelectedSymbol) selectScannerSymbol(window.fastDeepSelectedSymbol);

  loadUniverse();
})();
