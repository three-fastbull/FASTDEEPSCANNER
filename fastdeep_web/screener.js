/* คัดหุ้นจากเมกะเทรนด์ — เริ่มจากภาพใหญ่แล้วค่อยแคบลงหาบริษัท */
(() => {
  const elements = {
    view: document.getElementById("trendView"),
    subtitle: document.getElementById("trendSubtitle"),
    caveat: document.getElementById("trendCaveat"),
    count: document.getElementById("trendCount"),
    total: document.getElementById("trendTotal"),
    cards: document.getElementById("trendCards"),
    detail: document.getElementById("trendDetail"),
    industry: document.getElementById("trendIndustry"),
    roe: document.getElementById("trendRoe"),
    growth: document.getElementById("trendGrowth"),
    debt: document.getElementById("trendDebt"),
    search: document.getElementById("trendSearch"),
    reset: document.getElementById("trendReset"),
    body: document.getElementById("trendBody"),
  };

  if (!elements.view) return;

  const state = { data: null, trend: "", loading: false };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function number(value, suffix = "") {
    return value === null || value === undefined ? "-" : `${value}${suffix}`;
  }

  // ตัวเลขที่ผ่านเกณฑ์ในหลักสูตรถูกเน้นไว้ ให้กวาดตาเจอตัวที่น่าเปิดดูต่อได้เร็ว
  function toneFor(key, value) {
    if (value === null || value === undefined) return "unknown";
    if (key === "roe") return value >= 15 ? "ok" : value >= 8 ? "warn" : "bad";
    if (key === "growth") return value >= 10 ? "ok" : value >= 3 ? "warn" : "bad";
    if (key === "margin") return value >= 15 ? "ok" : value >= 5 ? "warn" : "bad";
    if (key === "debt") return value <= 1 ? "ok" : value <= 1.5 ? "warn" : "bad";
    return "unknown";
  }

  // การ์ดเก็บแค่ชื่อกับจำนวน ส่วนคำอธิบายยาวย้ายไปแถบเดียวใต้กริด
  // ถ้าใส่ไว้ในทุกการ์ดจะอ่านไม่ไหวและกวาดตาหาเทรนด์ที่ต้องการไม่เจอ
  function renderCards() {
    const trends = state.data.megatrends || [];
    elements.cards.innerHTML = [
      `<button class="trend-card ${state.trend ? "" : "is-active"}" type="button" data-trend="">
        <span class="trend-card-name">All Trends</span>
        <span class="trend-card-short">ดูทั้ง universe</span>
        <span class="trend-card-count">${state.data.total}</span>
      </button>`,
      ...trends.map((trend) => `<button class="trend-card ${state.trend === trend.key ? "is-active" : ""}" type="button" data-trend="${escapeHtml(trend.key)}">
        <span class="trend-card-name">${escapeHtml(trend.name)}</span>
        <span class="trend-card-short">${escapeHtml(trend.short)}</span>
        <span class="trend-card-count">${trend.count}</span>
      </button>`),
    ].join("");
    renderTrendDetail();
  }

  function renderTrendDetail() {
    const trend = (state.data.megatrends || []).find((item) => item.key === state.trend);
    if (!trend) {
      elements.detail.innerHTML = "";
      elements.detail.hidden = true;
      return;
    }
    elements.detail.hidden = false;
    elements.detail.innerHTML = `
      <div>
        <span>ทำไมเทรนด์นี้น่าสนใจ</span>
        <p>${escapeHtml(trend.thesis)}</p>
      </div>
      <div class="trend-detail-watch">
        <span>สิ่งที่ต้องระวัง</span>
        <p>${escapeHtml(trend.watch)}</p>
      </div>`;
  }

  function renderIndustryOptions() {
    const selected = elements.industry.value;
    const trend = (state.data.megatrends || []).find((item) => item.key === state.trend);
    // เลือกเทรนด์แล้วให้เหลือเฉพาะกลุ่มอุตสาหกรรมที่อยู่ในเทรนด์นั้น
    const allowed = trend ? new Set(trend.industries.map((item) => item.key)) : null;
    const industries = (state.data.industries || []).filter((item) => !allowed || allowed.has(item.key));
    elements.industry.innerHTML = [
      '<option value="ALL">ทุกกลุ่ม</option>',
      ...industries.map((item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)} (${item.count})</option>`),
    ].join("");
    elements.industry.value = industries.some((item) => item.key === selected) ? selected : "ALL";
  }

  function filtered() {
    const roe = Number(elements.roe.value) || null;
    const growth = Number(elements.growth.value) || null;
    const debt = Number(elements.debt.value) || null;
    const term = elements.search.value.trim().toLowerCase();
    const industry = elements.industry.value;
    return (state.data.companies || []).filter((company) => {
      if (state.trend && !company.megatrends.includes(state.trend)) return false;
      if (industry !== "ALL" && company.industry_group !== industry) return false;
      const quality = company.quality || {};
      if (roe !== null && !(quality.roe >= roe)) return false;
      if (growth !== null && !(quality.revenue_cagr >= growth)) return false;
      if (debt !== null && !(quality.debt_to_equity !== null && quality.debt_to_equity <= debt)) return false;
      if (term && !`${company.symbol} ${company.name}`.toLowerCase().includes(term)) return false;
      return true;
    });
  }

  function renderTable() {
    const rows = filtered();
    elements.count.textContent = rows.length;
    elements.total.textContent = `จากทั้งหมด ${state.data.total} บริษัท`;
    if (!rows.length) {
      elements.body.innerHTML = '<tr><td colspan="7">ไม่มีบริษัทที่ผ่านเงื่อนไขนี้ ลองผ่อนตัวกรองลง</td></tr>';
      return;
    }
    const sorted = rows.slice().sort((a, b) => (b.quality.revenue_cagr ?? -999) - (a.quality.revenue_cagr ?? -999));
    elements.body.innerHTML = sorted.map((company) => {
      const quality = company.quality || {};
      return `<tr>
        <th scope="row">
          <button class="trend-symbol" type="button" data-symbol="${escapeHtml(company.symbol)}">${escapeHtml(company.symbol)}</button>
          <small>${escapeHtml(company.name)}${company.reviewed ? " · ตรวจธุรกิจแล้ว" : ""}</small>
        </th>
        <td>${escapeHtml(company.industry_label)}<small>${escapeHtml(company.industry)}</small></td>
        <td data-tone="${toneFor("growth", quality.revenue_cagr)}">${number(quality.revenue_cagr, "%")}</td>
        <td data-tone="${toneFor("roe", quality.roe)}">${number(quality.roe, "%")}</td>
        <td data-tone="${toneFor("margin", quality.net_margin)}">${number(quality.net_margin, "%")}</td>
        <td data-tone="${toneFor("debt", quality.debt_to_equity)}">${number(quality.debt_to_equity, " เท่า")}</td>
        <td>${quality.statements || 0} ปี<small>${escapeHtml(quality.period || "")}</small></td>
      </tr>`;
    }).join("");
  }

  function render() {
    renderCards();
    renderIndustryOptions();
    renderTable();
  }

  async function load() {
    if (state.data || state.loading) return;
    state.loading = true;
    elements.body.innerHTML = '<tr><td colspan="7">กำลังจัดกลุ่มบริษัทตามเมกะเทรนด์...</td></tr>';
    try {
      const response = await fetch("/api/screener?market=US");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "โหลดข้อมูลไม่สำเร็จ");
      state.data = payload;
      elements.caveat.textContent = `${payload.basis} — ${payload.caveat}`;
      render();
    } catch (error) {
      elements.body.innerHTML = `<tr><td colspan="7">${escapeHtml(error.message)}</td></tr>`;
    } finally {
      state.loading = false;
    }
  }

  elements.cards.addEventListener("click", (event) => {
    const card = event.target.closest("[data-trend]");
    if (!card) return;
    state.trend = card.dataset.trend;
    render();
  });

  elements.body.addEventListener("click", (event) => {
    const button = event.target.closest(".trend-symbol");
    if (!button) return;
    // ส่งต่อให้หน้าข้อมูลบริษัทเหมือนกดจากตารางผลสแกน
    window.fastDeepSelectedSymbol = button.dataset.symbol;
    window.dispatchEvent(new CustomEvent("fastdeep:symbol-selected", {
      detail: { symbol: button.dataset.symbol, source: "screener" },
    }));
    const tab = document.querySelector('[data-view-target="profileView"]');
    if (tab) tab.click();
  });

  [elements.industry, elements.roe, elements.growth, elements.debt].forEach((control) => {
    control.addEventListener("change", renderTable);
  });
  elements.search.addEventListener("input", renderTable);
  elements.reset.addEventListener("click", () => {
    state.trend = "";
    elements.roe.value = "";
    elements.growth.value = "";
    elements.debt.value = "";
    elements.search.value = "";
    render();
  });

  document.querySelectorAll('[data-view-target="trendView"]').forEach((tab) => {
    tab.addEventListener("click", load);
  });
})();
