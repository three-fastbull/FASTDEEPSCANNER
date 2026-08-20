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
    annualHead: document.getElementById("annualFinancialHead"),
    annualBody: document.getElementById("annualFinancialBody"),
    quarterlyTitle: document.getElementById("quarterlyTitle"),
    quarterlySubtitle: document.getElementById("quarterlySubtitle"),
    quarterlyNote: document.getElementById("quarterlyPeriodNote"),
    quarterlyHead: document.getElementById("quarterlyFinancialHead"),
    quarterlyBody: document.getElementById("quarterlyFinancialBody"),
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

  function amount(value, metric) {
    if (value === null || value === undefined) return "-";
    if (metric === "basic_eps") return number(value, 2);
    return number(Number(value) / 1_000_000);
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
    if (viewId !== "scannerView" && state.financials?.symbol !== normalizedSymbol()) loadFinancials(false);
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
      state.selectedYear = payload.annual.at(-1)?.period_end.slice(0, 4) || null;
      renderFinancials();
      renderVi();
      window.dispatchEvent(new CustomEvent("fastdeep:financials-verified", {
        detail: { symbol: payload.symbol },
      }));
      status(`${payload.symbol} พร้อมใช้งาน (${payload.cache_status === "cached" ? "ใช้ข้อมูลที่บันทึกไว้" : "อัปเดตแล้ว"})`, "ready");
    } catch (error) {
      if (requestId !== state.financialRequestId) return;
      status(error.message || "ไม่สามารถโหลดงบการเงินได้", "error");
    } finally {
      if (requestId !== state.financialRequestId) return;
      elements.loadButton.disabled = false;
      elements.refreshButton.disabled = false;
    }
  }

  function financialCell(period, metric) {
    const year = period.period_end.slice(0, 4);
    return `<td><button type="button" class="financial-period-button" data-year="${year}" title="ดู Q1-Q4 ปี ${year}">${amount(period.metrics[metric], metric)}</button></td>`;
  }

  function ratioCell(period, key) {
    const year = period.period_end.slice(0, 4);
    const value = period.ratios[key];
    const formatted = key === "debt_to_equity" ? multiple(value) : percent(value);
    return `<td><button type="button" class="financial-period-button" data-year="${year}" title="ดู Q1-Q4 ปี ${year}">${formatted}</button></td>`;
  }

  function renderFinancials() {
    const data = state.financials;
    if (!data) return;
    const annual = data.annual || [];
    elements.title.textContent = `${data.symbol} - งบการเงินย้อนหลัง`;
    elements.subtitle.textContent = `${data.name} | ${data.market} | ${data.sector}`;
    elements.unit.textContent = `${data.unit} ${data.currency || ""}`.trim();
    elements.source.textContent = `${data.source} | ${data.cache_status === "cached" ? "Cache ล่าสุด" : "อัปเดตล่าสุด"}: ${new Date(data.fetched_at).toLocaleString("th-TH")}`;

    const latest = annual.at(-1) || { metrics: {}, ratios: {} };
    const kpis = [
      ["รายได้ล่าสุด", amount(latest.metrics.total_revenue, "total_revenue"), `${data.unit} ${data.currency || ""}`],
      ["กำไรสุทธิ", amount(latest.metrics.net_income, "net_income"), `${data.unit} ${data.currency || ""}`],
      ["ROE", percent(latest.ratios.roe), "ผลตอบแทนผู้ถือหุ้น"],
      ["D/E", multiple(latest.ratios.debt_to_equity), "หนี้สินต่อทุน"],
    ];
    elements.kpis.innerHTML = kpis.map(([label, value, note]) => (
      `<article class="financial-kpi"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note)}</small></article>`
    )).join("");

    elements.annualHead.innerHTML = `<tr><th scope="col">งวดงบการเงิน</th>${annual.map((period) => {
      const year = period.period_end.slice(0, 4);
      return `<th scope="col"><button class="year-header-button ${year === state.selectedYear ? "is-selected" : ""}" type="button" data-year="${year}">${year}<small>${period.period_end}</small></button></th>`;
    }).join("")}</tr>`;

    const rows = [];
    for (const section of data.sections || []) {
      rows.push(`<tr class="financial-section-row"><th colspan="${annual.length + 1}">${escapeHtml(section.title)}</th></tr>`);
      for (const metric of section.metrics) {
        rows.push(`<tr><th scope="row">${escapeHtml(data.metric_labels[metric] || metric)}</th>${annual.map((period) => financialCell(period, metric)).join("")}</tr>`);
      }
    }
    rows.push(`<tr class="financial-section-row"><th colspan="${annual.length + 1}">อัตราส่วนทางการเงินที่สำคัญ</th></tr>`);
    for (const [key, label] of Object.entries(data.ratio_labels || {})) {
      rows.push(`<tr><th scope="row">${escapeHtml(label)}</th>${annual.map((period) => ratioCell(period, key)).join("")}</tr>`);
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
    elements.quarterlyTitle.textContent = `${data.symbol} - รายไตรมาส ปี ${state.selectedYear}`;
    elements.quarterlySubtitle.textContent = "ตัวเลข Q4* ที่ไม่มีรายงานแยกจะคำนวณจากงบทั้งปีลบ Q1-Q3";
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
        rows.push(`<tr><th scope="row">${escapeHtml(data.metric_labels[metric] || metric)}</th>${quarters.map((quarter) => {
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
    if (actual === null || actual === undefined || target === null || target === undefined || target === 0) return null;
    const raw = options.inverse ? target / actual * 100 : actual / target * 100;
    return Math.max(0, Math.min(140, raw));
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
      <small>${progress === null ? "ไม่มีข้อมูลพอสำหรับประเมิน" : `ความคืบหน้า ${number(progress, 0)}%`}</small>
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
    const score = availableProgress.length ? Math.round(availableProgress.reduce((sum, value) => sum + value, 0) / availableProgress.length) : 0;

    elements.viTitle.textContent = `${data.symbol} - VI Thesis และ Financial Quality`;
    elements.viSubtitle.textContent = `${data.name} | งบ ${summary.period} | เป้าหมายปรับได้จากข้อมูลของคุณ`;
    elements.viScore.textContent = `${score}%`;
    elements.viScore.dataset.quality = score >= 100 ? "strong" : score >= 80 ? "watch" : "weak";
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
      return `<article class="vi-check">
        <span>${escapeHtml(check.label)}</span>
        <strong>${displayValue}</strong>
        <p>${trend === null || trend === undefined ? "ข้อมูลไม่พอเทียบช่วงเวลา" : `${check.cagr !== undefined ? "CAGR" : "เปลี่ยนแปลง"} ${percent(trend)}`}</p>
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
  window.addEventListener("fastdeep:symbol-selected", (event) => selectScannerSymbol(event.detail?.symbol));
  elements.symbolInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") loadFinancials(false);
  });
  elements.annualHead.addEventListener("click", (event) => {
    const button = event.target.closest("[data-year]");
    if (!button) return;
    state.selectedYear = button.dataset.year;
    renderFinancials();
  });
  elements.annualBody.addEventListener("click", (event) => {
    const button = event.target.closest("[data-year]");
    if (!button) return;
    state.selectedYear = button.dataset.year;
    renderFinancials();
  });
  [elements.targetRevenueCagr, elements.targetProfitCagr, elements.targetRoe, elements.targetDebtEquity]
    .forEach((input) => input.addEventListener("input", renderVi));

  if (window.fastDeepSelectedSymbol) selectScannerSymbol(window.fastDeepSelectedSymbol);

  loadUniverse();
})();
