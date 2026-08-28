(() => {
  const elements = {
    view: document.getElementById("hallView"),
    market: document.getElementById("hallMarket"),
    universe: document.getElementById("hallUniverse"),
    search: document.getElementById("hallSearch"),
    refresh: document.getElementById("hallRefresh"),
    status: document.getElementById("hallStatus"),
    summary: document.getElementById("hallSummary"),
    podium: document.getElementById("hallPodium"),
    body: document.getElementById("hallBody"),
    coverage: document.getElementById("hallCoverage"),
    methodology: document.getElementById("hallMethodology"),
  };
  if (!elements.view) return;

  const state = { loaded: false, leaders: [], requestId: 0 };
  const money = new Intl.NumberFormat("th-TH", { maximumFractionDigits: 0 });
  const decimal = new Intl.NumberFormat("th-TH", { maximumFractionDigits: 2 });

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function studyButton(symbol) {
    return `<button class="hall-study ghost-button" type="button" data-symbol="${escapeHtml(symbol)}">ศึกษาบริษัท</button>`;
  }

  function visibleLeaders() {
    const query = elements.search.value.trim().toLowerCase();
    if (!query) return state.leaders;
    return state.leaders.filter((item) =>
      item.symbol.toLowerCase().includes(query) || item.name.toLowerCase().includes(query),
    );
  }

  function renderPodium(leaders) {
    elements.podium.innerHTML = leaders.slice(0, 3).map((item, index) => `
      <article class="podium-item" data-place="${index + 1}">
        <span class="podium-rank">อันดับ ${item.rank}</span>
        <div><strong>${escapeHtml(item.symbol)}</strong><small>${escapeHtml(item.name)}</small></div>
        <p><b>${decimal.format(item.annualized_return_pct)}%</b> ต่อปี <span>XIRR ของแผน DCA</span></p>
        <dl><div><dt>มูลค่าปัจจุบัน</dt><dd>${money.format(item.ending_value)} บาท</dd></div><div><dt>ราคาหุ้น CAGR</dt><dd>${decimal.format(item.price_cagr_pct)}% ต่อปี</dd></div><div><dt>กำไรรวม/เงินที่ใส่</dt><dd>+${decimal.format(item.total_gain_pct)}%</dd></div><div><dt>เงินโตเป็น</dt><dd>${decimal.format(item.wealth_multiple)} เท่า</dd></div></dl>
        ${studyButton(item.symbol)}
      </article>`).join("");
  }

  function renderTable() {
    const leaders = visibleLeaders();
    if (!leaders.length) {
      elements.body.innerHTML = '<tr><td colspan="10" class="empty-row">ไม่พบหุ้นตามคำค้นหานี้</td></tr>';
      return;
    }
    elements.body.innerHTML = leaders.map((item) => `
      <tr>
        <td><span class="rank-cell">${item.rank}</span></td>
        <th scope="row"><strong>${escapeHtml(item.symbol)}</strong><small>${escapeHtml(item.name)}</small></th>
        <td>${escapeHtml(item.market)}<small>${escapeHtml(item.index_groups || "-")}</small></td>
        <td class="return-cell">${decimal.format(item.annualized_return_pct)}%</td>
        <td>${decimal.format(item.price_cagr_pct)}%</td>
        <td>${money.format(item.ending_value)} บาท</td>
        <td>${money.format(item.total_invested)} บาท</td>
        <td>${money.format(item.profit)} บาท<small>+${decimal.format(item.total_gain_pct)}% ของเงินที่ใส่</small></td>
        <td class="drawdown-cell">-${decimal.format(item.max_monthly_drawdown_pct)}%</td>
        <td>${studyButton(item.symbol)}</td>
      </tr>`).join("");
  }

  function renderMethodology(methodology, exclusions = []) {
    const labels = {
      period: "ช่วงเวลา",
      purchase_timing: "จังหวะลงทุน",
      ranking_metric: "วิธีจัดอันดับ",
      price_basis: "ราคาที่ใช้",
      drawdown: "ความเสี่ยงย้อนหลัง",
      corporate_actions: "ความต่อเนื่องของหุ้น",
      excluded: "ข้อจำกัด",
    };
    elements.methodology.innerHTML = Object.entries(labels).map(([key, label]) => `
      <div><strong>${label}</strong><p>${escapeHtml(methodology[key] || "-")}</p></div>`).join("");
    for (const item of exclusions) {
      const row = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = `${item.symbol} · ไม่รวมในอันดับ 10 ปี`;
      const reason = document.createElement("p");
      reason.textContent = item.reason;
      row.append(title, reason);
      if (String(item.source_url || "").startsWith("https://")) {
        const link = document.createElement("a");
        link.href = item.source_url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = "เอกสารอ้างอิง";
        row.append(link);
      }
      elements.methodology.append(row);
    }
  }

  function render(payload) {
    state.leaders = payload.leaders || [];
    if (!payload.available) {
      elements.status.textContent = payload.message || "ยังไม่มีข้อมูล Hall of Fame";
      elements.summary.innerHTML = '<p class="hall-empty">ระบบยังไม่มีข้อมูลรายเดือนย้อนหลัง 10 ปีที่ผ่านการตรวจครบ</p>';
      elements.podium.innerHTML = "";
      elements.body.innerHTML = '<tr><td colspan="10" class="empty-row">กำลังรอข้อมูลราคา 10 ปี</td></tr>';
      elements.coverage.textContent = "ไม่มีข้อมูลที่ผ่านการตรวจในกลุ่มที่เลือก";
      renderMethodology(payload.methodology || {}, payload.corporate_action_exclusions || []);
      return;
    }
    const updated = payload.source?.updated_at ? new Date(payload.source.updated_at).toLocaleString("th-TH") : "-";
    elements.status.textContent = `ข้อมูลถึง ${payload.as_of || "-"} · อัปเดต ${updated}`;
    elements.summary.innerHTML = `
      <div><span>ประวัติผ่านเกณฑ์ 120 เดือน</span><strong>${money.format(payload.evaluated)} <small>/ ${money.format(payload.universe_count)}</small></strong></div>
      <div><span>ผ่านเกณฑ์ 15% ต่อปี</span><strong>${money.format(payload.qualified)}</strong></div>
      <div><span>เงินลงทุนตามแผน</span><strong>${state.leaders[0] ? money.format(state.leaders[0].total_invested) : "-"}</strong><small>บาทต่อหุ้นตลอดช่วง</small></div>
      <div><span>วันที่ประเมิน</span><strong>${escapeHtml(payload.as_of || "-")}</strong></div>`;
    elements.coverage.textContent = `จัดอันดับ ${payload.qualified} จาก ${payload.evaluated} บริษัทที่ประวัติผ่านเกณฑ์ · ไม่นำ ${payload.insufficient_history} บริษัทที่ประวัติหรือราคาปรับแล้วไม่ครบมาจัดอันดับ`;
    if (payload.excluded_corporate_actions) {
      elements.coverage.textContent += ` · แยกออกอีก ${payload.excluded_corporate_actions} บริษัทจากการยกเลิกหุ้นเดิม`;
    }
    renderPodium(state.leaders);
    renderTable();
    renderMethodology(payload.methodology || {}, payload.corporate_action_exclusions || []);
  }

  async function loadHall(force = false) {
    if (state.loaded && !force) return;
    const requestId = ++state.requestId;
    state.loaded = false;
    state.leaders = [];
    elements.podium.innerHTML = "";
    elements.body.innerHTML = '<tr><td colspan="10" class="empty-row">กำลังคำนวณ...</td></tr>';
    elements.coverage.textContent = "";
    elements.summary.innerHTML = "";
    elements.refresh.disabled = true;
    elements.status.textContent = "กำลังคำนวณ DCA 10 ปี...";
    const query = new URLSearchParams({
      market: elements.market.value,
      universe: elements.universe.value,
      min_return: "15",
    });
    try {
      const response = await fetch(`/api/hall-of-fame?${query}`);
      const payload = await response.json();
      if (requestId !== state.requestId) return;
      if (!response.ok) throw new Error(payload.error || "โหลด Hall of Fame ไม่สำเร็จ");
      state.loaded = true;
      render(payload);
    } catch (error) {
      if (requestId !== state.requestId) return;
      elements.status.textContent = error.message || "โหลด Hall of Fame ไม่สำเร็จ";
      elements.body.innerHTML = '<tr><td colspan="10" class="empty-row">โหลดข้อมูลไม่สำเร็จ กรุณาลองใหม่</td></tr>';
    } finally {
      if (requestId === state.requestId) elements.refresh.disabled = false;
    }
  }

  document.querySelectorAll('[data-view-target="hallView"]').forEach((tab) => {
    tab.addEventListener("click", () => loadHall());
  });
  elements.market.addEventListener("change", () => loadHall(true));
  elements.universe.addEventListener("change", () => loadHall(true));
  elements.refresh.addEventListener("click", () => loadHall(true));
  elements.search.addEventListener("input", renderTable);

  elements.view.addEventListener("click", (event) => {
    const button = event.target.closest(".hall-study");
    if (!button) return;
    const symbol = button.dataset.symbol;
    window.fastDeepSelectedSymbol = symbol;
    window.dispatchEvent(new CustomEvent("fastdeep:symbol-selected", { detail: { symbol, source: "hall-of-fame" } }));
    const profileTab = document.querySelector('[data-view-target="profileView"]');
    if (profileTab) profileTab.click();
  });
})();
