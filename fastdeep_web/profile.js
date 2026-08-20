/* หน้า "รู้จักหุ้นตัวนี้" — เรียงตามกรอบ ONE Investor
   ประเภทหุ้น -> Financial Quality Filter 4 ด่าน -> Margin of Safety -> เชิงคุณภาพ */
(() => {
  const elements = {
    button: document.getElementById("profileButton"),
    view: document.getElementById("profileView"),
    eyebrow: document.getElementById("profileEyebrow"),
    title: document.getElementById("profileTitle"),
    subtitle: document.getElementById("profileSubtitle"),
    price: document.getElementById("profilePrice"),
    priceNote: document.getElementById("profilePriceNote"),
    verdict: document.getElementById("profileVerdict"),
    identity: document.getElementById("profileIdentity"),
    stages: document.getElementById("profileStages"),
    valuation: document.getElementById("profileValuation"),
    qualitative: document.getElementById("profileQualitative"),
    flow: document.getElementById("profileFlow"),
    financialLink: document.getElementById("profileFinancialLink"),
  };

  if (!elements.view) return;

  const state = { symbol: null, profile: null, requestId: 0 };

  const compact = new Intl.NumberFormat("th-TH", { maximumFractionDigits: 1 });
  const precise = new Intl.NumberFormat("th-TH", { maximumFractionDigits: 2 });

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function num(value, digits = 2) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
    return (digits === 1 ? compact : precise).format(Number(value));
  }

  // ตัวเลขงบเป็นหน่วยเต็ม แสดงเป็นล้านเพื่อให้อ่านได้ในบรรทัดเดียว
  function millions(value) {
    if (value === null || value === undefined) return "-";
    return compact.format(Number(value) / 1_000_000);
  }

  function stateIcon(itemState) {
    if (itemState === "pass") return "✓";
    if (itemState === "fail") return "✕";
    return "?";
  }

  /* เส้นแนวโน้มเล็ก ๆ วาดจากตัวเลขจริง ไม่ใช้ไลบรารีภายนอก */
  function sparkline(values, tone = "ok") {
    const points = values.map((value, index) => [index, value]).filter(([, value]) => value !== null && value !== undefined);
    if (points.length < 2) return "";
    const ys = points.map(([, value]) => Number(value));
    const min = Math.min(...ys);
    const max = Math.max(...ys);
    const span = max - min || Math.abs(max) || 1;
    const width = 132;
    const height = 34;
    const stepX = width / (values.length - 1);
    const path = points
      .map(([index, value], order) => {
        const x = (index * stepX).toFixed(1);
        const y = (height - ((Number(value) - min) / span) * (height - 6) - 3).toFixed(1);
        return `${order === 0 ? "M" : "L"}${x},${y}`;
      })
      .join(" ");
    return `<svg class="spark" data-tone="${tone}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true"><path d="${path}" fill="none" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
  }

  function seriesRow(label, years, values, formatter, tone) {
    const cells = values
      .map((value) => `<td>${value === null || value === undefined ? "-" : formatter(value)}</td>`)
      .join("");
    return `<tr><th scope="row">${escapeHtml(label)}</th>${cells}<td class="spark-cell">${sparkline(values, tone)}</td></tr>`;
  }

  function renderVerdict(profile) {
    const verdict = profile.verdict;
    if (!verdict) {
      elements.verdict.innerHTML = `<p class="decision-empty">${escapeHtml(profile.reason || "ยังไม่มีข้อมูลพอสรุป")}</p>`;
      elements.verdict.dataset.key = "";
      return;
    }
    elements.verdict.dataset.key = verdict.key;
    const checks = verdict.checklist
      .map(
        (item) => `<li data-state="${item.passed ? "pass" : "fail"}">
          <span>${item.passed ? "✓" : "✕"}</span>
          <div><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.detail)}</small></div>
        </li>`,
      )
      .join("");
    elements.verdict.innerHTML = `
      <div class="verdict-headline">
        <span class="verdict-tag">สรุปการตัดสินใจ</span>
        <strong>${escapeHtml(verdict.label)}</strong>
        <p>${escapeHtml(verdict.note)}</p>
      </div>
      <ul class="verdict-checklist">${checks}</ul>`;
  }

  function renderIdentity(profile) {
    const lynch = profile.lynch_type;
    const trend = profile.megatrend || {};
    const cards = [];
    if (lynch) {
      cards.push(`<article class="identity-card" data-kind="${escapeHtml(lynch.key)}">
        <span>ประเภทหุ้นตาม Peter Lynch</span>
        <strong>${escapeHtml(lynch.label)}</strong>
        <p>${escapeHtml(lynch.description)}</p>
        ${lynch.reasons && lynch.reasons.length ? `<ul>${lynch.reasons.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
        <p class="identity-watch"><b>สิ่งที่ต้องระวัง</b> ${escapeHtml(lynch.watch || "")}</p>
      </article>`);
    }
    cards.push(`<article class="identity-card" data-kind="trend">
      <span>เมกะเทรนด์ที่เกี่ยวข้อง</span>
      <strong>${escapeHtml(trend.label || "-")}</strong>
      <p>${escapeHtml(trend.note || "")}</p>
      <p class="identity-watch"><b>กลุ่มอุตสาหกรรม</b> ${escapeHtml(profile.sector || "-")}</p>
    </article>`);

    const series = profile.series || {};
    cards.push(`<article class="identity-card" data-kind="series">
      <span>ตัวเลขหลักย้อนหลัง</span>
      <div class="table-scroll">
        <table class="series-table">
          <thead><tr><th>รายการ</th>${(series.years || []).map((year) => `<th>${escapeHtml(year)}</th>`).join("")}<th>แนวโน้ม</th></tr></thead>
          <tbody>
            ${seriesRow(`รายได้ (ล้าน ${profile.reporting_currency})`, series.years, series.revenue || [], millions, "ok")}
            ${seriesRow(`กำไรสุทธิ (ล้าน ${profile.reporting_currency})`, series.years, series.net_income || [], millions, "ok")}
            ${seriesRow(`EPS (${profile.reporting_currency}/หุ้น)`, series.years, series.eps || [], (value) => num(value, 2), "ok")}
            ${seriesRow("ROE (%)", series.years, series.roe || [], (value) => num(value, 1), "gold")}
            ${seriesRow("อัตรากำไรสุทธิ (%)", series.years, series.net_margin || [], (value) => num(value, 1), "gold")}
            ${seriesRow("หนี้สินต่อทุน (เท่า)", series.years, series.debt_to_equity || [], (value) => num(value, 2), "warn")}
          </tbody>
        </table>
      </div>
    </article>`);
    elements.identity.innerHTML = cards.join("");
  }

  function renderStages(profile) {
    elements.stages.innerHTML = (profile.stages || [])
      .map((stage) => {
        const criteria = stage.criteria
          .map(
            (item) => `<li data-state="${item.state}">
              <span class="criterion-icon">${stateIcon(item.state)}</span>
              <div>
                <strong>${escapeHtml(item.label)}</strong>
                <p class="criterion-value">${escapeHtml(item.value)}</p>
                <p class="criterion-target">เกณฑ์ผ่าน: ${escapeHtml(item.target)}</p>
                ${item.note ? `<p class="criterion-note">${escapeHtml(item.note)}</p>` : ""}
              </div>
            </li>`,
          )
          .join("");
        return `<article class="stage-card" data-passed="${stage.passed}" data-key="${escapeHtml(stage.key)}">
          <header>
            <span class="stage-number">${stage.number}</span>
            <div>
              <strong>${escapeHtml(stage.title)}</strong>
              <small>${escapeHtml(stage.subtitle)}</small>
            </div>
            <span class="stage-badge">${stage.passed ? "ผ่านด่านนี้" : "ไม่ผ่านด่านนี้"}</span>
          </header>
          <p class="stage-goal">${escapeHtml(stage.goal)}</p>
          <ul class="criteria-list">${criteria}</ul>
          ${stage.needs_manual_check ? '<p class="stage-manual">ด่านนี้มีข้อที่ข้อมูลสาธารณะไม่ครอบคลุม ต้องเปิดเอกสารตรวจเอง</p>' : ""}
        </article>`;
      })
      .join("");
  }

  function renderValuation(profile) {
    const valuation = profile.valuation || {};
    if (!valuation.available) {
      elements.valuation.innerHTML = '<p class="decision-empty">ยังประเมินมูลค่าไม่ได้จากงบชุดนี้</p>';
      return;
    }
    const currency = valuation.currency || "";
    const mos = valuation.margin_of_safety_pct;
    const target = valuation.target_pct || 20;
    // แถบนี้ให้เห็นว่าส่วนลดปัจจุบันห่างจากเกณฑ์ 20% แค่ไหน ไม่ใช่แค่ตัวเลขลอย ๆ
    const fill = mos === null || mos === undefined ? 0 : Math.max(0, Math.min(100, (mos / target) * 100));
    const tone = mos === null || mos === undefined ? "unknown" : mos >= target ? "ok" : mos > 0 ? "warn" : "bad";

    const methods = (valuation.methods || [])
      .map(
        (method) => `<li data-skipped="${Boolean(method.skipped)}">
          <div>
            <strong>${escapeHtml(method.name)}</strong>
            <small>${escapeHtml(method.detail)}</small>
            <small class="method-note">${escapeHtml(method.note)}</small>
          </div>
          <span>${method.fair_value === null || method.fair_value === undefined ? "ไม่ใช้" : `${num(method.fair_value)} ${escapeHtml(currency)}`}</span>
        </li>`,
      )
      .join("");

    const history = (profile.pe_history || [])
      .map((row) => `<tr><th>${escapeHtml(row.year)}</th><td>${num(row.price)}</td><td>${num(row.eps)}</td><td>${num(row.pe)}</td></tr>`)
      .join("");

    elements.valuation.innerHTML = `
      <article class="mos-card" data-tone="${tone}">
        <span>Margin of Safety</span>
        <strong>${mos === null || mos === undefined ? "-" : `${num(mos, 1)}%`}</strong>
        <div class="mos-track"><span style="width:${fill}%"></span></div>
        <p>เกณฑ์ที่ควรมีคืออย่างน้อย ${target}% ยิ่งสูงยิ่งปลอดภัย</p>
        <dl>
          <div><dt>ราคาปัจจุบัน</dt><dd>${num(valuation.price)} ${escapeHtml(currency)}</dd></div>
          <div><dt>มูลค่าที่เหมาะสม</dt><dd>${num(valuation.fair_value)} ${escapeHtml(currency)}</dd></div>
          <div><dt>ช่วงที่ประเมินได้</dt><dd>${num(valuation.fair_value_low)} - ${num(valuation.fair_value_high)}</dd></div>
          <div><dt>มูลค่าทางบัญชีต่อหุ้น</dt><dd>${num(valuation.book_value_per_share)} ${escapeHtml(currency)}</dd></div>
        </dl>
        ${valuation.estimates_agree ? "" : `<p class="mos-warning">วิธีประเมินให้ผลห่างกัน ${valuation.spread} เท่า ตัวเลขกลางจึงยังไม่น่าเชื่อถือพอใช้ตัดสินใจ</p>`}
        <p class="mos-note">${escapeHtml(valuation.note || "")}</p>
      </article>
      <article class="method-card">
        <h4>วิธีประเมินมูลค่าที่ใช้</h4>
        <ul class="method-list">${methods}</ul>
        ${history ? `<h4>P/E ที่ตลาดเคยให้หุ้นตัวนี้</h4>
        <div class="table-scroll">
          <table class="series-table">
            <thead><tr><th>ปี</th><th>ราคา ณ สิ้นงวด</th><th>EPS</th><th>P/E</th></tr></thead>
            <tbody>${history}</tbody>
          </table>
        </div>` : ""}
      </article>`;
  }

  function renderQualitative(profile) {
    const qualitative = profile.qualitative || {};
    const recorded = qualitative.recorded;
    const forces = (profile.five_forces || [])
      .map(
        (force) => `<article class="force-card">
          <span>${force.number}</span>
          <div>
            <strong>${escapeHtml(force.title)}</strong>
            <small>${escapeHtml(force.english)}</small>
            <ul>${force.questions.map((question) => `<li>${escapeHtml(question)}</li>`).join("")}</ul>
            <p class="force-risk">${escapeHtml(force.risk)}</p>
          </div>
        </article>`,
      )
      .join("");

    elements.qualitative.innerHTML = `
      <article class="analyst-card" data-recorded="${recorded}">
        <h4>สิ่งที่บันทึกไว้แล้ว</h4>
        <dl>
          <div><dt>ความได้เปรียบในการแข่งขัน (Moat)</dt><dd>${escapeHtml(qualitative.moat || "ยังไม่ได้บันทึก")}</dd></div>
          <div><dt>แนวโน้มธุรกิจ</dt><dd>${escapeHtml(qualitative.ai_trend || "ยังไม่ได้บันทึก")}</dd></div>
          <div><dt>สถานะงานวิจัย</dt><dd>${escapeHtml(qualitative.status || "Watch")}</dd></div>
          <div><dt>Thesis</dt><dd>${escapeHtml(qualitative.thesis || "ยังไม่ได้บันทึก")}</dd></div>
        </dl>
        <p class="analyst-hint">${recorded
          ? "บันทึกครบแล้ว คะแนนในหน้า Scanner จึงนับคุณภาพธุรกิจเข้าไปด้วย"
          : "ยังไม่ได้บันทึก Moat และแนวโน้มธุรกิจ กลับไปกรอกในหน้า Scanner ใต้หัวข้อบันทึกงานวิจัย"}</p>
      </article>
      <div class="force-grid">
        <h4>Five Forces — ห้าแรงกดดันที่กำหนดว่าธุรกิจนี้ทำกำไรได้แค่ไหน</h4>
        ${forces}
      </div>`;
  }

  function renderFlow(profile) {
    elements.flow.innerHTML = (profile.flow || [])
      .map(
        (step) => `<li>
          <strong>${escapeHtml(step.name)} — ${escapeHtml(step.label)}</strong>
          <p>${escapeHtml(step.question)}</p>
        </li>`,
      )
      .join("");
  }

  function renderProfile(profile) {
    state.profile = profile;
    elements.eyebrow.textContent = `${profile.market || "-"} · ${profile.sector || "-"}`;
    elements.title.textContent = `${profile.symbol} — ${profile.name}`;
    elements.price.textContent = `${num(profile.last_price)} ${profile.trading_currency || ""}`;
    elements.financialLink.href = "#";
    elements.financialLink.dataset.symbol = profile.symbol;

    if (!profile.available) {
      elements.subtitle.textContent = profile.reason || "ยังไม่มีงบการเงินพอสำหรับประเมิน";
      elements.priceNote.textContent = `ราคา ณ ${profile.price_as_of || "-"}`;
      renderVerdict(profile);
      elements.identity.innerHTML = "";
      elements.stages.innerHTML = "";
      elements.valuation.innerHTML = "";
      renderQualitative(profile);
      renderFlow(profile);
      return;
    }

    elements.subtitle.textContent =
      `งบการเงิน ${profile.statement_period} สกุล ${profile.reporting_currency_label} · ` +
      `ผ่าน Financial Quality Filter ${profile.passed_stages} จาก ${profile.total_stages} ด่าน`;
    elements.priceNote.textContent = profile.fx_adjusted
      ? `ณ ${profile.price_as_of} · แปลงเป็น ${profile.price_in_reporting} ${profile.reporting_currency} ก่อนเทียบกับงบ`
      : `ณ ${profile.price_as_of} · สกุลเดียวกับงบการเงิน`;

    renderVerdict(profile);
    renderIdentity(profile);
    renderStages(profile);
    renderValuation(profile);
    renderQualitative(profile);
    renderFlow(profile);
  }

  async function loadProfile(symbol) {
    if (!symbol) return;
    const requestId = ++state.requestId;
    state.symbol = symbol;
    elements.verdict.innerHTML = `<p class="decision-empty">กำลังประเมิน ${escapeHtml(symbol)} จากงบการเงินจริง...</p>`;
    try {
      const response = await fetch(`/api/stock-profile?symbol=${encodeURIComponent(symbol)}`);
      const payload = await response.json();
      if (requestId !== state.requestId) return;
      if (!response.ok) throw new Error(payload.error || "โหลดข้อมูลหุ้นไม่สำเร็จ");
      renderProfile(payload);
    } catch (error) {
      if (requestId !== state.requestId) return;
      elements.verdict.innerHTML = `<p class="decision-empty">${escapeHtml(error.message)}</p>`;
    }
  }

  function showProfileView() {
    document.querySelectorAll(".app-view").forEach((view) => {
      view.classList.toggle("is-hidden", view.id !== "profileView");
    });
    document.querySelectorAll(".nav-tab").forEach((tab) => {
      tab.classList.toggle("is-active", tab.dataset.viewTarget === "profileView");
    });
  }

  elements.button.addEventListener("click", () => {
    const symbol = window.fastDeepSelectedSymbol;
    if (!symbol) return;
    showProfileView();
    if (state.symbol !== symbol || !state.profile) loadProfile(symbol);
  });

  document.querySelectorAll('[data-view-target="profileView"]').forEach((tab) => {
    tab.addEventListener("click", () => {
      const symbol = window.fastDeepSelectedSymbol;
      if (symbol && (state.symbol !== symbol || !state.profile)) loadProfile(symbol);
    });
  });

  elements.financialLink.addEventListener("click", (event) => {
    event.preventDefault();
    const tab = document.querySelector('[data-view-target="financialsView"]');
    if (tab) tab.click();
  });

  window.addEventListener("fastdeep:symbol-selected", (event) => {
    const symbol = event.detail?.symbol;
    // โหลดใหม่เฉพาะตอนที่ผู้ใช้กำลังเปิดหน้านี้อยู่ จะได้ไม่ยิงคำขอโดยไม่จำเป็น
    if (symbol && !elements.view.classList.contains("is-hidden")) loadProfile(symbol);
    else if (symbol !== state.symbol) state.profile = null;
  });
})();
