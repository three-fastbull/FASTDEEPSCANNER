/* Company research, growth, financial quality, valuation, and thesis share one selected symbol. */
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
    growth: document.getElementById("profileGrowthSnapshot"),
    business: document.getElementById("profileBusiness"),
    competition: document.getElementById("profileCompetition"),
    identity: document.getElementById("profileIdentity"),
    stages: document.getElementById("profileStages"),
    valuation: document.getElementById("profileValuation"),
    qualitative: document.getElementById("profileQualitative"),
    thesis: document.getElementById("profileThesis"),
    flow: document.getElementById("profileFlow"),
    financialLink: document.getElementById("profileFinancialLink"),
    researchForm: document.getElementById("profileResearchForm"),
    researchSave: document.getElementById("profileResearchSave"),
    researchStatus: document.getElementById("profileResearchStatus"),
    businessSummary: document.getElementById("profileBusinessSummary"),
    revenueModel: document.getElementById("profileRevenueModel"),
    revenueSegments: document.getElementById("profileRevenueSegments"),
    keyCustomers: document.getElementById("profileKeyCustomers"),
    competitors: document.getElementById("profileCompetitors"),
    moatEvidence: document.getElementById("profileMoatEvidence"),
    researchMoat: document.getElementById("profileResearchMoat"),
    researchTrend: document.getElementById("profileResearchTrend"),
    researchDecision: document.getElementById("profileResearchDecision"),
    catalysts: document.getElementById("profileCatalysts"),
    risks: document.getElementById("profileRisks"),
    invalidation: document.getElementById("profileInvalidation"),
    sourceUrls: document.getElementById("profileSourceUrls"),
    researchThesis: document.getElementById("profileResearchThesis"),
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

  function stateIcon(itemState) {
    if (itemState === "pass") return "✓";
    if (itemState === "fail") return "✕";
    return "?";
  }

  const FORMATTERS = {
    millions: (value) => compact.format(Number(value) / 1_000_000),
    decimal: (value) => num(value, 2),
    percent: (value) => `${num(value, 1)}%`,
    multiple: (value) => `${num(value, 2)}x`,
  };

  function splitResearchLines(value) {
    return String(value || "").split(/\r?\n|;/).map((item) => item.trim()).filter(Boolean);
  }

  function researchList(value, emptyMessage) {
    const items = splitResearchLines(value);
    if (!items.length) return `<p class="research-empty">${escapeHtml(emptyMessage)}</p>`;
    return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
  }

  function sourceLinks(value) {
    const items = Array.isArray(value) ? value : splitResearchLines(value).map((url) => ({ url }));
    if (!items.length) return '<p class="research-empty">ยังไม่มีแหล่งข้อมูลอ้างอิง</p>';
    return `<ul class="source-list">${items.map((item) => {
      try {
        const url = new URL(item.url);
        if (!["http:", "https:"].includes(url.protocol)) throw new Error("unsupported");
        return `<li><a href="${escapeHtml(url.href)}" target="_blank" rel="noreferrer">${escapeHtml(item.title || url.hostname)}</a></li>`;
      } catch (_) {
        return `<li>${escapeHtml(item.title || item.url || "")}</li>`;
      }
    }).join("")}</ul>`;
  }

  function citations(ids, reference) {
    const sources = (reference.sources || []).filter((source) => (ids || []).includes(source.id));
    return sources.length ? `<div class="reference-citations">${sourceLinks(sources)}</div>` : "";
  }

  const ORIGIN_MARKERS = {
    journal: ["journal-marker", "บันทึกของคุณ"],
    filing: ["filing-marker", "ยกจากแบบที่ยื่น ยังไม่ทบทวน"],
  };

  // ผู้อ่านต้องแยกออกทันทีว่าข้อความมาจากบันทึกของตัวเอง จากงานวิจัยที่ทบทวนแล้ว
  // หรือยกมาดิบ ๆ จากเอกสารที่บริษัทยื่น
  function journalMarker(business, key) {
    const marker = ORIGIN_MARKERS[business.field_origins?.[key]];
    return marker ? `<small class="${marker[0]}">${marker[1]}</small>` : "";
  }

  function filingNote(business) {
    const filing = business.filing || {};
    if (!filing.available || !filing.source_url) return "";
    const origins = business.field_origins || {};
    const used = Object.values(origins).filter((origin) => origin === "filing").length;
    if (!used) return "";
    const period = filing.period || filing.filed_at || "";
    return `<div class="filing-note">
      <strong>ข้อความบางช่องยกมาจากแบบ ${escapeHtml(filing.form || "10-K")} ที่ยื่นต่อ SEC</strong>
      <span>${escapeHtml(filing.entity_name || "")}${period ? ` · งวด ${escapeHtml(period)}` : ""}${filing.industry ? ` · ${escapeHtml(filing.industry)}` : ""}</span>
      <span>เป็นข้อความต้นฉบับภาษาอังกฤษที่ยังไม่ผ่านการเรียบเรียงหรือทบทวน ใช้เป็นจุดตั้งต้นเท่านั้น</span>
      ${sourceLinks([{ url: filing.source_url, title: `เปิดแบบ ${filing.form || "10-K"} ฉบับเต็ม` }])}
    </div>`;
  }

  function renderRevenueBreakdown(business) {
    const reference = business.reference || {};
    const breakdown = reference.revenue_breakdown;
    if (!breakdown || business.field_origins?.revenue_segments === "journal") {
      return researchList(business.revenue_segments, "ยังไม่มีข้อมูลแยกรายได้ที่อ้างอิงได้");
    }
    const segments = breakdown.segments || [];
    const amounts = segments.filter((segment) => Number.isFinite(segment.amount));
    return `<ul class="revenue-breakdown">${segments.map((segment) => {
      const share = Number.isFinite(segment.share_pct) ? Math.max(0, Math.min(100, segment.share_pct)) : null;
      return `<li><div><strong>${escapeHtml(segment.name)}</strong>${share !== null ? `<b>${num(share, 1)}%</b>` : ""}</div>
        ${share !== null ? `<span class="segment-track" aria-hidden="true"><i style="width:${share}%"></i></span>` : ""}
        ${segment.description ? `<small>${escapeHtml(segment.description)}</small>` : ""}</li>`;
    }).join("")}</ul>
    <p class="breakdown-basis">ฐาน: ${escapeHtml(breakdown.basis)}</p>
    ${breakdown.note ? `<p class="breakdown-note">${escapeHtml(breakdown.note)}</p>` : ""}
    ${amounts.length ? `<details class="business-extra"><summary>จำนวนเงิน (${escapeHtml(breakdown.unit)} ${escapeHtml(breakdown.currency)})</summary>
      <dl>${amounts.map((segment) => `<div><dt>${escapeHtml(segment.name)}</dt><dd>${num(segment.amount)}</dd></div>`).join("")}
      <div><dt>รวม</dt><dd>${num(breakdown.total)}</dd></div></dl></details>` : ""}`;
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
        <span class="verdict-tag">สรุปก่อนพิจารณาซื้อ · ผ่าน ${verdict.passed_checks ?? 0} จาก ${verdict.total_checks ?? 0} เงื่อนไขใหญ่</span>
        <strong>${escapeHtml(verdict.label)}</strong>
        <p>${escapeHtml(verdict.note)}</p>
      </div>
      <ul class="verdict-checklist">${checks}</ul>
      <p class="verdict-context">Financial Quality Filter 4 ด่านอยู่ภายในเงื่อนไขใหญ่ข้อแรก ไม่ได้นับเป็นด่านตัดสินใจอีกชุดหนึ่ง</p>`;
  }

  function growthCard(label, item, note = "") {
    if (!item?.available) {
      return `<article><span>${escapeHtml(label)}</span><strong>-</strong><small>ข้อมูลไม่พอคำนวณ</small></article>`;
    }
    const annualized = item.cagr_pct ?? item.annualized_return_pct;
    const total = item.total_change_pct ?? item.total_return_pct;
    const tone = Number(annualized) >= 0 ? "ok" : "bad";
    return `<article data-tone="${tone}">
      <span>${escapeHtml(label)}</span>
      <strong>${Number(annualized) >= 0 ? "+" : ""}${num(annualized, 1)}% <i>ต่อปี</i></strong>
      <small>รวม ${Number(total) >= 0 ? "+" : ""}${num(total, 1)}% ใน ${num(item.years, 1)} ปี${note ? ` · ${escapeHtml(note)}` : ""}</small>
    </article>`;
  }

  function renderGrowth(profile) {
    const growth = profile.growth_snapshot || {};
    const stock = growth.stock_return || profile.historical_return || {};
    const priceNote = stock.basis === "adjusted_close" ? "ราคาปรับสิทธิ" : "ราคาปิด";
    elements.growth.innerHTML = [
      growthCard("รายได้โตเฉลี่ย", growth.revenue),
      growthCard("กำไรสุทธิโตเฉลี่ย", growth.net_income),
      growthCard("EPS โตเฉลี่ย", growth.eps),
      growthCard("ผลตอบแทนหุ้นเฉลี่ย", stock, priceNote),
    ].join("");
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

    const summaries = (profile.series_summary || []).slice(0, 8);
    cards.push(`<article class="identity-card" data-kind="series">
      <span>ตัวเลขที่ใช้ตัดสินใจ</span>
      <div class="profile-kpi-grid">${summaries.map((row) => {
        const format = FORMATTERS[row.format] || FORMATTERS.decimal;
        const values = (row.values || []).filter((value) => value !== null && value !== undefined);
        const latest = values.length ? format(values[values.length - 1]) : "-";
        const trend = row.trend || {};
        return `<div class="profile-kpi"><small>${escapeHtml(row.label)}</small><strong>${escapeHtml(latest)}</strong><span data-tone="${escapeHtml(trend.tone || "unknown")}">${escapeHtml(trend.label || "-")}</span></div>`;
      }).join("")}</div>
      <a class="inline-link" href="#" data-profile-financial-link>เปิดงบย้อนหลังทุกบรรทัด</a>
    </article>`);
    elements.identity.innerHTML = cards.join("");
  }

  function renderBusiness(profile) {
    const business = profile.business || {};
    const reference = business.reference || {};
    const verified = Boolean(business.verified);
    const hasReference = Boolean(reference.available);
    const reviewed = reference.reviewed_at ? new Date(`${reference.reviewed_at}T00:00:00`).toLocaleDateString("th-TH") : "";
    const filing = business.filing || {};
    const usesFiling = Object.values(business.field_origins || {}).includes("filing");
    const status = hasReference
      ? (reference.needs_review ? "มีข้อมูลอ้างอิงเดิม · ถึงรอบทบทวน" : "มีข้อมูลธุรกิจอ้างอิงแล้ว")
      : verified ? "มีบันทึกตรวจธุรกิจครบแล้ว"
        : usesFiling ? "มีข้อความจากแบบที่ยื่น · ยังไม่ผ่านการทบทวน"
          : "ยังไม่มีข้อมูลธุรกิจอ้างอิง";
    const context = hasReference
      ? `${reference.period} · ตรวจแหล่งข้อมูล ${reviewed}`
      : reference.status === "error" ? "ฐานข้อมูลธุรกิจอ่านไม่ได้ · บันทึกส่วนตัวยังอยู่"
        : usesFiling ? `${profile.symbol} ยังไม่อยู่ในฐานวิจัย ${reference.catalog_count || 0} บริษัท · แสดงข้อความต้นฉบับจาก ${filing.form || "10-K"} แทน`
          : `${profile.symbol} ยังไม่อยู่ในฐานวิจัย ${reference.catalog_count || 0} บริษัท`;
    elements.business.innerHTML = `
      <div class="research-state" data-verified="${verified}" data-reference="${hasReference}">
        <strong>${status}</strong><span>${escapeHtml(context)}</span>
      </div>
      <div class="business-layout">
        <article class="business-summary"><span>บริษัททำอะไร ${journalMarker(business, "summary")}</span><p>${escapeHtml(business.summary || "ยังไม่มีคำอธิบายธุรกิจจากแหล่งข้อมูลที่ตรวจสอบได้")}</p></article>
        <article><span>บริษัทหาเงินอย่างไร ${journalMarker(business, "revenue_model")}</span><p>${escapeHtml(business.revenue_model || "ยังไม่ได้บันทึกรูปแบบรายได้")}</p></article>
        <article><span>รายได้แต่ละทาง ${journalMarker(business, "revenue_segments")}</span>${renderRevenueBreakdown(business)}</article>
        <article><span>ลูกค้าหลัก ${journalMarker(business, "key_customers")}</span><p>${escapeHtml(business.key_customers || "ยังไม่ได้ตรวจลูกค้าหลักและความกระจุกตัว")}</p></article>
      </div>
      ${hasReference ? `<div class="business-sources"><strong>แหล่งอ้างอิงบริษัท</strong>${sourceLinks((reference.sources || []).filter((source) => (reference.source_ids || []).includes(source.id)))}</div>` : ""}
      ${business.field_origins?.source_urls === "journal" ? `<div class="business-sources"><strong>แหล่งข้อมูลในบันทึก</strong>${sourceLinks(business.source_urls)}</div>` : ""}
      ${filingNote(business)}`;
  }

  function renderCompetition(profile) {
    const business = profile.business || {};
    const qualitative = profile.qualitative || {};
    const reference = business.reference || {};
    const peers = reference.available && business.field_origins?.competitors !== "journal" ? reference.peers || [] : [];
    const evidence = reference.available && business.field_origins?.moat_evidence !== "journal" ? reference.evidence || [] : [];
    const kinds = { reported: "ข้อมูลรายงาน", company_claim: "บริษัทระบุ", analysis: "ข้อวิเคราะห์" };
    elements.competition.innerHTML = `
      <div class="competition-layout">
        <article><span>คู่แข่ง / บริษัทเทียบเคียง ${journalMarker(business, "competitors")}</span>
          ${peers.length ? `<ul class="peer-list">${peers.map((peer) => `<li>
            <strong>${escapeHtml(peer.name)}${peer.symbol ? ` <small>${escapeHtml(peer.symbol)}</small>` : ""}</strong>
            <p>${escapeHtml(peer.overlap)}</p><p class="peer-compare">ประเด็นเปรียบเทียบ: ${escapeHtml(peer.compare)}</p>
            ${citations(peer.source_ids, reference)}</li>`).join("")}</ul>` : researchList(business.competitors, "ยังไม่มีรายชื่อคู่แข่งที่อ้างอิงได้")}
        </article>
        <article class="moat-evidence"><span>ความได้เปรียบและข้อจำกัด ${journalMarker(business, "moat_evidence")}</span>
          <p>${escapeHtml(business.moat_evidence || "ยังไม่มีหลักฐานเพียงพอประเมินความได้เปรียบ")}</p>
          ${evidence.length ? `<ul class="evidence-list">${evidence.map((item) => `<li>
            <div><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(kinds[item.kind] || "ข้อวิเคราะห์")}</small></div>
            <p>${escapeHtml(item.detail)}</p>${citations(item.source_ids, reference)}</li>`).join("")}</ul>` : ""}
          <p class="moat-review">Moat ที่คุณประเมิน: <strong>${escapeHtml(qualitative.moat || "ยังไม่ประเมิน")}</strong></p>
        </article>
      </div>
      ${peers.length ? '<p class="comparison-note">กลุ่มเปรียบเทียบคัดจากธุรกิจที่ทับซ้อน ไม่ใช่อันดับความเก่งหรือหลักฐานว่าใครมี Moat สูงกว่า</p>' : ""}
      ${reference.industry_note ? `<p class="industry-research-note">${escapeHtml(reference.industry_note)}</p>` : ""}
      ${(reference.watch_items || []).length ? `<details class="business-extra research-followup"><summary>ประเด็นที่ยังต้องติดตาม</summary>${researchList(reference.watch_items.join("\n"), "")}</details>` : ""}`;
  }

  function renderThesis(profile) {
    const business = profile.business || {};
    const qualitative = profile.qualitative || {};
    elements.thesis.innerHTML = `<div class="thesis-case-grid">
      <article><span>Thesis</span><p>${escapeHtml(qualitative.thesis || "ยังไม่มี Thesis ที่บันทึกไว้")}</p></article>
      <article data-tone="ok"><span>ตัวเร่งการเติบโต</span>${researchList(business.catalysts, "ยังไม่ได้ระบุตัวเร่ง")}</article>
      <article data-tone="bad"><span>ความเสี่ยงหลัก</span>${researchList(business.risks, "ยังไม่ได้ระบุความเสี่ยง")}</article>
      <article data-tone="warn"><span>เมื่อไรต้องยอมรับว่าคิดผิด</span><p>${escapeHtml(business.invalidation || "ยังไม่มีเงื่อนไขยกเลิก Thesis")}</p></article>
    </div>`;
  }

  function renderResearchEditor(profile) {
    const business = profile.business || {};
    const qualitative = profile.qualitative || {};
    const journal = profile.research;
    // Loading source material must not silently turn it into a saved personal judgement.
    elements.businessSummary.value = (journal ? journal.business_summary : business.summary) || "";
    elements.revenueModel.value = (journal ? journal.revenue_model : business.revenue_model) || "";
    elements.revenueSegments.value = (journal ? journal.revenue_segments : business.revenue_segments) || "";
    elements.keyCustomers.value = (journal ? journal.key_customers : business.key_customers) || "";
    elements.competitors.value = (journal ? journal.competitors : business.competitors) || "";
    elements.moatEvidence.value = (journal ? journal.moat_evidence : business.moat_evidence) || "";
    elements.researchMoat.value = qualitative.moat || "";
    elements.researchTrend.value = qualitative.ai_trend || "";
    elements.researchDecision.value = qualitative.status || "Watch";
    elements.catalysts.value = (journal ? journal.catalysts : business.catalysts) || "";
    elements.risks.value = (journal ? journal.risks : business.risks) || "";
    elements.invalidation.value = (journal ? journal.invalidation : business.invalidation) || "";
    elements.sourceUrls.value = (journal ? journal.source_urls : business.source_urls) || "";
    elements.researchThesis.value = qualitative.thesis || "";
    elements.researchStatus.textContent = qualitative.updated_at
      ? `บันทึกล่าสุด ${new Date(qualitative.updated_at).toLocaleString("th-TH")}`
      : "ยังไม่ได้บันทึกงานวิจัย";
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
        return `<details class="stage-card" data-passed="${stage.passed}" data-key="${escapeHtml(stage.key)}" ${stage.passed ? "" : "open"}>
          <summary>
            <span class="stage-number">${stage.number}</span>
            <div>
              <strong>${escapeHtml(stage.title)}</strong>
              <small>${escapeHtml(stage.subtitle)}</small>
            </div>
            <span class="stage-badge">${stage.passed ? (stage.needs_manual_check ? "ผ่านตัวเลข" : "ผ่านด่านนี้") : "ไม่ผ่านด่านนี้"}</span>
          </summary>
          <div class="stage-detail"><p class="stage-goal">${escapeHtml(stage.goal)}</p>
            <ul class="criteria-list">${criteria}</ul>
            ${stage.needs_manual_check ? '<p class="stage-manual">ด่านนี้มีข้อที่ข้อมูลสาธารณะไม่ครอบคลุม ต้องเปิดเอกสารตรวจเอง</p>' : ""}
          </div>
        </details>`;
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
    renderBusiness(profile);
    renderCompetition(profile);
    renderThesis(profile);
    renderResearchEditor(profile);
    renderGrowth(profile);

    if (!profile.available) {
      elements.subtitle.textContent = profile.reason || "ยังไม่มีงบการเงินพอสำหรับประเมิน";
      elements.priceNote.textContent = `ราคา ณ ${profile.price_as_of || "-"}`;
      renderVerdict(profile);
      elements.identity.innerHTML = '<p class="decision-empty">ยังไม่มีงบย้อนหลังพอสรุปตัวเลข</p>';
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

  async function saveCompanyResearch(event) {
    event.preventDefault();
    if (!state.symbol || state.profile?.symbol !== state.symbol) return;
    const savedSymbol = state.symbol;
    elements.researchSave.disabled = true;
    elements.researchStatus.textContent = "กำลังบันทึก...";
    const current = state.profile?.qualitative || {};
    try {
      const response = await fetch("/api/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: savedSymbol,
          status: elements.researchDecision.value,
          note: current.note || "",
          moat: elements.researchMoat.value,
          ai_trend: elements.researchTrend.value,
          thesis: elements.researchThesis.value,
          business_summary: elements.businessSummary.value,
          revenue_model: elements.revenueModel.value,
          revenue_segments: elements.revenueSegments.value,
          key_customers: elements.keyCustomers.value,
          competitors: elements.competitors.value,
          moat_evidence: elements.moatEvidence.value,
          catalysts: elements.catalysts.value,
          risks: elements.risks.value,
          invalidation: elements.invalidation.value,
          source_urls: elements.sourceUrls.value,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "บันทึกงานวิจัยไม่สำเร็จ");
      if (state.symbol !== savedSymbol) return;
      elements.researchStatus.textContent = payload.company_profile_verified
        ? "บันทึกแล้ว · ข้อมูลธุรกิจผ่านเกณฑ์ตรวจครบ"
        : "บันทึกแล้ว · ยังมีช่องสำคัญที่ต้องตรวจเพิ่ม";
      await loadProfile(savedSymbol);
    } catch (error) {
      if (state.symbol === savedSymbol) elements.researchStatus.textContent = error.message || "บันทึกงานวิจัยไม่สำเร็จ";
    } finally {
      elements.researchSave.disabled = !state.profile;
    }
  }

  async function loadProfile(symbol) {
    if (!symbol) return;
    const requestId = ++state.requestId;
    state.symbol = symbol;
    state.profile = null;
    elements.researchSave.disabled = true;
    elements.title.textContent = symbol;
    elements.subtitle.textContent = "กำลังโหลดข้อมูลบริษัท...";
    elements.price.textContent = "-";
    elements.priceNote.textContent = "";
    for (const key of ["business", "competition", "thesis", "growth", "identity", "stages", "valuation", "qualitative", "flow"]) elements[key].textContent = "";
    elements.verdict.innerHTML = `<p class="decision-empty">กำลังประเมิน ${escapeHtml(symbol)} จากงบการเงินจริง...</p>`;
    try {
      const response = await fetch(`/api/stock-profile?symbol=${encodeURIComponent(symbol)}`);
      const payload = await response.json();
      if (requestId !== state.requestId) return;
      if (!response.ok) throw new Error(payload.error || "โหลดข้อมูลหุ้นไม่สำเร็จ");
      renderProfile(payload);
      elements.researchSave.disabled = false;
    } catch (error) {
      if (requestId !== state.requestId) return;
      elements.subtitle.textContent = "ยังโหลดข้อมูลบริษัทไม่สำเร็จ";
      elements.verdict.innerHTML = `<p class="decision-empty">${escapeHtml(error.message)}</p>`;
    }
  }

  function showProfileView() {
    document.querySelector('[data-view-target="profileView"]').click();
  }

  elements.button.addEventListener("click", () => {
    const symbol = window.fastDeepSelectedSymbol;
    if (!symbol) return;
    showProfileView();
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

  elements.view.addEventListener("click", (event) => {
    const link = event.target.closest("[data-profile-financial-link]");
    if (!link) return;
    event.preventDefault();
    const tab = document.querySelector('[data-view-target="financialsView"]');
    if (tab) tab.click();
  });

  elements.researchForm.addEventListener("submit", saveCompanyResearch);

  window.addEventListener("fastdeep:symbol-selected", (event) => {
    const symbol = event.detail?.symbol;
    // โหลดใหม่เฉพาะตอนที่ผู้ใช้กำลังเปิดหน้านี้อยู่ จะได้ไม่ยิงคำขอโดยไม่จำเป็น
    if (symbol && !elements.view.classList.contains("is-hidden")) loadProfile(symbol);
    else if (symbol !== state.symbol) state.profile = null;
  });
})();
