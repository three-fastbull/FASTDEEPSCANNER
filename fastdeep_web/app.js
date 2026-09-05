const state = {
  results: [],
  selectedSymbol: null,
  criteriaQuery: "",
  imageIndex: null,
  dataHealth: null,
  scanRequestId: 0,
  symbolRequestId: 0,
  detailPayload: null,
};
const MAX_VISIBLE_RESULTS = 50;

const elements = {
  scanStatus: document.getElementById("scanStatus"),
  dataSourceNote: document.getElementById("dataSourceNote"),
  marketSelect: document.getElementById("marketSelect"),
  universeSelect: document.getElementById("universeSelect"),
  timeframeSelect: document.getElementById("timeframeSelect"),
  scoreRange: document.getElementById("scoreRange"),
  scoreValue: document.getElementById("scoreValue"),
  scanButton: document.getElementById("scanButton"),
  csvButton: document.getElementById("csvButton"),
  resultsBody: document.getElementById("resultsBody"),
  generatedAt: document.getElementById("generatedAt"),
  metricCount: document.getElementById("metricCount"),
  metricBest: document.getElementById("metricBest"),
  metricA: document.getElementById("metricA"),
  metricMarket: document.getElementById("metricMarket"),
  detailTitle: document.getElementById("detailTitle"),
  detailSubtitle: document.getElementById("detailSubtitle"),
  detailGrade: document.getElementById("detailGrade"),
  chart: document.getElementById("priceChart"),
  tradingViewButton: document.getElementById("tradingViewButton"),
  reportButton: document.getElementById("reportButton"),
  riskPlan: document.getElementById("riskPlan"),
  fundamentalBox: document.getElementById("fundamentalBox"),
  agentNotes: document.getElementById("agentNotes"),
  warningList: document.getElementById("warningList"),
  chartImageInput: document.getElementById("chartImageInput"),
  chartDropZone: document.getElementById("chartDropZone"),
  chartFileName: document.getElementById("chartFileName"),
  imageScanButton: document.getElementById("imageScanButton"),
  chartImagePreview: document.getElementById("chartImagePreview"),
  imageMatches: document.getElementById("imageMatches"),
  dataHealth: document.getElementById("dataHealth"),
  dataHealthMessage: document.getElementById("dataHealthMessage"),
  dataHealthFacts: document.getElementById("dataHealthFacts"),
  decisionSummary: document.getElementById("decisionSummary"),
  researchStatus: document.getElementById("researchStatus"),
  researchMoat: document.getElementById("researchMoat"),
  researchTrend: document.getElementById("researchTrend"),
  researchFairValue: document.getElementById("researchFairValue"),
  researchThesis: document.getElementById("researchThesis"),
  researchNote: document.getElementById("researchNote"),
  researchSaveButton: document.getElementById("researchSaveButton"),
  researchSavedAt: document.getElementById("researchSavedAt"),
  paperTradeButton: document.getElementById("paperTradeButton"),
  paperTradeStatus: document.getElementById("paperTradeStatus"),
  evidenceTimeframe: document.getElementById("evidenceTimeframe"),
  evidenceMethod: document.getElementById("evidenceMethod"),
  evidenceHead: document.getElementById("evidenceHead"),
  evidenceBody: document.getElementById("evidenceBody"),
  evidenceSubtitle: document.getElementById("evidenceSubtitle"),
  journalKpis: document.getElementById("journalKpis"),
  journalBody: document.getElementById("journalBody"),
  journalScore: document.getElementById("journalScore"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function patternValues() {
  return [...document.querySelectorAll(".pattern-controls input:checked")].map((input) => input.value);
}

function criteriaQuery() {
  const params = new URLSearchParams();
  params.set("market", elements.marketSelect.value);
  params.set("universe", elements.universeSelect.value);
  params.set("timeframe", elements.timeframeSelect.value);
  params.set("patterns", patternValues().join(","));
  params.set("min_score", elements.scoreRange.value);
  params.set("min_liquidity", "40");
  state.criteriaQuery = params.toString();
  return state.criteriaQuery;
}

function weekKey(dateText) {
  const date = new Date(`${dateText}T00:00:00`);
  const firstDay = new Date(date.getFullYear(), 0, 1);
  const dayNumber = Math.floor((date - firstDay) / 86400000) + 1;
  const week = Math.ceil((dayNumber + firstDay.getDay()) / 7);
  return `${date.getFullYear()}-W${String(week).padStart(2, "0")}`;
}

function aggregateCandles(candles, timeframe) {
  if (timeframe === "D") return candles;
  const groups = new Map();
  for (const candle of candles) {
    const date = new Date(`${candle.date}T00:00:00`);
    const key = timeframe === "W"
      ? weekKey(candle.date)
      : `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
    const current = groups.get(key);
    if (!current) {
      groups.set(key, { ...candle });
      continue;
    }
    current.date = candle.date;
    current.high = Math.max(current.high, candle.high);
    current.low = Math.min(current.low, candle.low);
    current.close = candle.close;
    current.volume += candle.volume;
  }
  return [...groups.values()];
}

function aggregateSeries(series, timeframe) {
  if (timeframe === "D") return series;
  const groups = new Map();
  for (const point of series) {
    const date = new Date(`${point.date}T00:00:00`);
    const key = timeframe === "W"
      ? weekKey(point.date)
      : `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
    groups.set(key, point);
  }
  return [...groups.values()];
}

function resample(values, length = 64) {
  if (!values.length) return [];
  if (values.length === 1) return Array(length).fill(values[0]);
  const output = [];
  for (let idx = 0; idx < length; idx += 1) {
    const position = idx * (values.length - 1) / (length - 1);
    const left = Math.floor(position);
    const right = Math.min(values.length - 1, left + 1);
    const mix = position - left;
    output.push(values[left] * (1 - mix) + values[right] * mix);
  }
  return output;
}

function zscore(values) {
  const mean = values.reduce((sum, value) => sum + value, 0) / Math.max(1, values.length);
  const variance = values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / Math.max(1, values.length);
  const stdev = Math.sqrt(variance) || 1;
  return values.map((value) => (value - mean) / stdev);
}

function correlation(a, b) {
  const n = Math.min(a.length, b.length);
  if (!n) return -1;
  let dot = 0;
  for (let idx = 0; idx < n; idx += 1) dot += a[idx] * b[idx];
  return dot / n;
}

function interpolateMissing(path) {
  const values = [...path];
  let last = null;
  for (let idx = 0; idx < values.length; idx += 1) {
    if (!Number.isFinite(values[idx])) continue;
    if (last === null) {
      for (let fill = 0; fill < idx; fill += 1) values[fill] = values[idx];
    } else if (idx - last > 1) {
      const start = values[last];
      const end = values[idx];
      for (let fill = last + 1; fill < idx; fill += 1) {
        const mix = (fill - last) / (idx - last);
        values[fill] = start * (1 - mix) + end * mix;
      }
    }
    last = idx;
  }
  if (last === null) return [];
  for (let idx = last + 1; idx < values.length; idx += 1) values[idx] = values[last];
  return values;
}

function extractImageShape(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const image = new Image();
      image.onload = () => {
        const width = 96;
        const height = 72;
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(image, 0, 0, width, height);
        const pixels = ctx.getImageData(0, 0, width, height).data;
        const path = [];
        for (let x = 0; x < width; x += 1) {
          let weightedY = 0;
          let weight = 0;
          for (let y = 4; y < height - 4; y += 1) {
            const pixel = (y * width + x) * 4;
            const r = pixels[pixel];
            const g = pixels[pixel + 1];
            const b = pixels[pixel + 2];
            const max = Math.max(r, g, b);
            const min = Math.min(r, g, b);
            const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
            const saturation = max === 0 ? 0 : (max - min) / max;
            const signal = saturation > 0.18 || luminance < 120;
            if (signal) {
              const score = Math.max(1, saturation * 4 + (255 - luminance) / 96);
              weightedY += (height - 1 - y) * score;
              weight += score;
            }
          }
          path.push(weight ? weightedY / weight : NaN);
        }
        const cleaned = interpolateMissing(path);
        if (!cleaned.length) reject(new Error("อ่านทรงกราฟจากรูปไม่ได้"));
        else resolve(zscore(resample(cleaned, 64)));
      };
      image.onerror = () => reject(new Error("เปิดรูปไม่ได้"));
      image.src = reader.result;
    };
    reader.onerror = () => reject(new Error("อ่านไฟล์รูปไม่ได้"));
    reader.readAsDataURL(file);
  });
}

async function loadImageIndex() {
  if (state.imageIndex) return state.imageIndex;
  const response = await fetch("/api/image-index");
  if (!response.ok) throw new Error("โหลดฐานข้อมูลรูปทรงกราฟไม่ได้");
  const payload = await response.json();
  state.imageIndex = payload.symbols || [];
  return state.imageIndex;
}

function scanImageMatches(uploadShape, indexRows) {
  const market = elements.marketSelect.value;
  const universe = elements.universeSelect.value;
  const timeframe = elements.timeframeSelect.value;
  const matches = [];
  for (const item of indexRows) {
    const groups = (item.index_groups || "").split("|");
    if (market !== "ALL" && item.market !== market) continue;
    if (universe !== "ALL" && !groups.includes(universe)) continue;
    const points = aggregateSeries(item.series || [], timeframe).map((point) => point.close);
    if (points.length < 12) continue;
    const shape = zscore(resample(points, 64));
    const corr = correlation(uploadShape, shape);
    const score = Math.max(0, Math.min(100, (corr + 1) * 50));
    matches.push({ ...item, score });
  }
  return matches.sort((a, b) => b.score - a.score).slice(0, 8);
}

function renderImageMatches(matches) {
  if (!matches.length) {
    elements.imageMatches.innerHTML = "<p>ไม่พบ asset ที่เทียบได้ ลองเปลี่ยนตลาด/Universe หรือแนบรูปที่เห็นกราฟชัดขึ้น</p>";
    return;
  }
  const scanSymbols = new Set(state.results.map((result) => result.symbol));
  elements.imageMatches.innerHTML = matches.map((match) => {
    const inScan = scanSymbols.has(match.symbol) ? "อยู่ในผลสแกน" : "ยังไม่เข้า pattern filter";
    return `
      <article class="image-match-item">
        <span class="image-match-score">${match.score.toFixed(1)}%</span>
        <div>
          <strong>${match.symbol}</strong>
          <span>${match.name} | ${match.market} | ${match.index_groups || "-"}</span>
          <span>${inScan}</span>
        </div>
        <div class="image-match-actions">
          <button class="ghost-button image-profile-button" type="button" data-symbol="${escapeHtml(match.symbol)}">ข้อมูลบริษัท</button>
          <a class="ghost-button" href="${match.tradingview_url}" target="_blank" rel="noreferrer">TradingView</a>
        </div>
      </article>
    `;
  }).join("");
}

function setStatus(text) {
  elements.scanStatus.textContent = text;
}

function healthFact(label, value, tone = "") {
  return `<span class="health-fact" data-tone="${tone}"><b>${escapeHtml(label)}</b>${escapeHtml(value)}</span>`;
}

function renderDataHealth(health, financialHealth = null, payload = {}) {
  state.dataHealth = health || null;
  if (!health) return;
  const latest = health.latest_candle_date || "-";
  const scannerAsOf = health.scanner_as_of_date || latest;
  const freshness = payload.symbol_freshness;
  const fx = payload.fx_health;
  const facts = [
    healthFact("กลุ่มสแกน ", health.universe && health.universe !== "ALL" ? health.universe : health.market && health.market !== "ALL" ? health.market : "ทุกตลาด"),
    healthFact("EOD ที่ใช้สแกน ", scannerAsOf, health.can_publish ? "ok" : "bad"),
    healthFact("แท่งล่าสุดในไฟล์ ", latest),
    healthFact("ผู้ให้บริการ ", health.source || "-"),
    healthFact("หุ้นที่มีราคา ", `${health.symbols_succeeded}/${health.symbols_requested}`),
  ];
  if (freshness) {
    const checked = health.symbols_fresh == null ? freshness.checked : health.symbols_requested;
    const fresh = health.symbols_fresh == null ? freshness.fresh : health.symbols_fresh;
    const stale = Math.max(0, checked - fresh);
    facts.push(healthFact(
      "หุ้นที่ผู้ให้บริการส่งถึงวันสแกน ",
      `${fresh}/${checked}${stale ? ` (รอแท่งล่าสุด ${stale} ตัว)` : ""}`,
      stale ? "warn" : "ok",
    ));
  }
  if (financialHealth) {
    if (["running", "updating"].includes(financialHealth.state)) {
      facts.push(healthFact(
        "กำลังอัปเดตงบ ",
        `${financialHealth.symbols_processed || 0}/${financialHealth.update_symbols_requested || financialHealth.symbols_requested}`,
        "warn",
      ));
    }
    facts.push(healthFact(
      "หุ้นที่มีไฟล์งบย้อนหลัง ",
      `${financialHealth.cached_symbols}/${financialHealth.symbols_requested}`,
      financialHealth.cached_symbols >= financialHealth.symbols_requested * 0.95 ? "ok" : "warn",
    ));
    facts.push(healthFact(
      "งบรายปีครบ 5 ปี ",
      `${financialHealth.annual_5y_symbols || 0}/${financialHealth.symbols_requested}`,
      financialHealth.annual_5y_symbols >= financialHealth.symbols_requested * 0.95 ? "ok" : "warn",
    ));
    const usCoverage = financialHealth.by_market?.US;
    if (usCoverage?.symbols) {
      facts.push(healthFact(
        "งบสหรัฐครบ 5 ปี + Q1-Q4 ",
        `${usCoverage.complete || 0}/${usCoverage.symbols}`,
        usCoverage.complete >= usCoverage.symbols * 0.85 ? "ok" : "warn",
      ));
    }
    if ((financialHealth.symbols_requested || 0) > (usCoverage?.symbols || 0)) {
      facts.push(healthFact(
        "งบจีน ฮ่องกง และไทย ",
        "แสดงตามงวดที่ตลาดเผยแพร่ ไม่ถือ Q ที่ไม่มีเป็นงานค้าง",
      ));
    }
    const secCount = financialHealth.by_source?.["SEC EDGAR"] || 0;
    const usTotal = financialHealth.by_market?.US?.symbols || 0;
    const secUpdate = financialHealth.sec_update || {};
    if (usTotal || secUpdate.symbols_requested) {
      const secTarget = usTotal || secCount;
      const progress = secUpdate.state === "running"
        ? ` · รอบนี้ ${secUpdate.symbols_processed || 0}/${secUpdate.symbols_requested || 0}`
        : secUpdate.state === "failed" ? " · รอบล่าสุดเชื่อมต่อไม่ได้" : "";
      const secValue = `${secCount}/${secTarget}${progress}`;
      facts.push(healthFact(
        "งบทางการ SEC ",
        secValue,
        secUpdate.state === "failed" ? "bad" : (secCount >= secTarget && secTarget ? "ok" : "warn"),
      ));
    }
  }
  if (fx) {
    facts.push(healthFact("อัตราแลกเปลี่ยน ", `${fx.rates} สกุล · ${fx.state}`, fx.state === "ready" ? "ok" : "warn"));
  }
  elements.dataHealthMessage.textContent = health.can_publish
    ? `${health.message} — ส่งออกรายชื่อ Candidate ได้`
    : `${health.message} — ปิดการส่งออก Candidate ไว้จนกว่าข้อมูลจะพร้อม`;
  elements.dataHealthFacts.innerHTML = facts.join("");
  elements.dataHealth.dataset.state = health.state || "unknown";
  elements.csvButton.classList.toggle("is-disabled", !health.can_publish);
  elements.csvButton.setAttribute("aria-disabled", String(!health.can_publish));
  elements.csvButton.title = health.can_publish ? "ส่งออกผลสแกน" : health.message;
}

async function loadResearch(symbol) {
  const response = await fetch(`/api/research?symbol=${encodeURIComponent(symbol)}`);
  if (!response.ok || state.selectedSymbol !== symbol) return;
  const item = await response.json();
  elements.researchStatus.value = item.status || "Watch";
  elements.researchMoat.value = item.moat || "";
  elements.researchTrend.value = item.ai_trend || "";
  elements.researchFairValue.value = item.fair_value ? String(item.fair_value) : "";
  elements.researchThesis.value = item.thesis || "";
  elements.researchNote.value = item.note || "";
  elements.researchSavedAt.textContent = item.updated_at
    ? `บันทึก ${new Date(item.updated_at).toLocaleString("th-TH")}`
    : "ยังไม่ได้บันทึก";
}

async function saveResearch() {
  if (!state.selectedSymbol) return;
  elements.researchSaveButton.disabled = true;
  try {
    const response = await fetch("/api/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        symbol: state.selectedSymbol,
        status: elements.researchStatus.value,
        note: elements.researchNote.value,
        moat: elements.researchMoat.value,
        ai_trend: elements.researchTrend.value,
        fair_value: elements.researchFairValue.value,
        thesis: elements.researchThesis.value,
      }),
    });
    const item = await response.json();
    if (!response.ok) throw new Error(item.error || "บันทึกสถานะไม่ได้");
    elements.researchSavedAt.textContent = `บันทึก ${new Date(item.updated_at).toLocaleString("th-TH")}`;
    // Business quality feeds the score, so the row has to be recomputed here.
    await runScan();
  } catch (error) {
    elements.researchSavedAt.textContent = error.message || "บันทึกสถานะไม่ได้";
  } finally {
    elements.researchSaveButton.disabled = false;
  }
}

const VERIFICATION_SHORT = {
  technical: "กราฟ",
  financial: "กราฟ+งบ",
  valuation: "กราฟ+งบ+มูลค่า",
  full: "ครบทุกด้าน",
};

function scoreClass(decision) {
  if (decision.includes("Candidate") || decision.includes("Watchlist")) return "good";
  if (decision.includes("Reject") || decision.includes("ไม่สด")) return "bad";
  return "warn";
}

function renderMetrics(results) {
  elements.metricCount.textContent = results.length;
  elements.metricBest.textContent = results.length ? results[0].final_score.toFixed(1) : "0";
  elements.metricA.textContent = results.filter((item) => item.grade === "A" || item.grade === "A+").length;
  const counts = results.reduce((acc, item) => {
    acc[item.market] = (acc[item.market] || 0) + 1;
    return acc;
  }, {});
  const leader = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  elements.metricMarket.textContent = leader ? leader[0] : "-";
}

function renderTable(results) {
  elements.resultsBody.innerHTML = "";
  if (!results.length) {
    const coverage = window.fastDeepUniverse?.selection();
    const message = coverage && !coverage.price_available
      ? "มีรายชื่อในกลุ่มนี้แล้ว แต่ยังไม่มีราคาสำหรับสแกน"
      : "ไม่พบหุ้นที่เข้าเงื่อนไขในกลุ่มและ Timeframe นี้";
    elements.resultsBody.innerHTML = `<tr><td colspan="6" class="empty-row">${message}</td></tr>`;
    return;
  }
  for (const result of results.slice(0, MAX_VISIBLE_RESULTS)) {
    const topPattern = result.patterns[0];
    const row = document.createElement("tr");
    row.dataset.symbol = result.symbol;
    row.innerHTML = `
      <td class="symbol-cell"><strong>${escapeHtml(result.symbol)}</strong><span>${escapeHtml(result.name)} · ${escapeHtml(result.currency || "")}</span></td>
      <td><span class="pattern-chip">${topPattern ? escapeHtml(topPattern.label) : "-"}</span></td>
      <td><strong>${escapeHtml(result.grade)}</strong></td>
      <td>${result.final_score.toFixed(1)}<small class="cap-note">/${Math.round(result.score_cap)}</small></td>
      <td class="verify-cell" data-level="${escapeHtml(result.verification_level)}">${escapeHtml(VERIFICATION_SHORT[result.verification_level] || "-")}</td>
      <td class="decision ${scoreClass(result.decision)}">${escapeHtml(result.decision)}</td>
    `;
    row.addEventListener("click", () => loadSymbol(result.symbol));
    elements.resultsBody.appendChild(row);
  }
}

function renderDefinitionList(target, rows) {
  target.innerHTML = "";
  for (const [label, value] of rows) {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = value;
    target.appendChild(dt);
    target.appendChild(dd);
  }
}

function drawChart(candles, result) {
  const canvas = elements.chart;
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.floor((rect.width || 640) * dpr));
  canvas.height = Math.floor(320 * dpr);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const width = canvas.width / dpr;
  const height = canvas.height / dpr;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fbfcfe";
  ctx.fillRect(0, 0, width, height);

  if (!candles.length) return;

  const pad = { left: 48, right: 18, top: 22, bottom: 58 };
  const chartW = width - pad.left - pad.right;
  const chartH = height - pad.top - pad.bottom;
  const highs = candles.map((c) => c.high);
  const lows = candles.map((c) => c.low);
  const maxPrice = Math.max(...highs);
  const minPrice = Math.min(...lows);
  const span = Math.max(maxPrice - minPrice, 0.01);
  const y = (price) => pad.top + (maxPrice - price) / span * chartH;
  const x = (idx) => pad.left + idx / Math.max(1, candles.length - 1) * chartW;

  ctx.strokeStyle = "#dbe3ee";
  ctx.lineWidth = 1;
  ctx.font = "11px Arial";
  ctx.fillStyle = "#64748b";
  for (let grid = 0; grid <= 4; grid += 1) {
    const yy = pad.top + chartH * grid / 4;
    ctx.beginPath();
    ctx.moveTo(pad.left, yy);
    ctx.lineTo(width - pad.right, yy);
    ctx.stroke();
    const price = maxPrice - span * grid / 4;
    ctx.fillText(price.toFixed(2), 8, yy + 4);
  }

  const candleW = Math.max(1, chartW / candles.length * 0.58);
  candles.forEach((candle, idx) => {
    const xx = x(idx);
    const up = candle.close >= candle.open;
    ctx.strokeStyle = up ? "#15803d" : "#b91c1c";
    ctx.fillStyle = up ? "#22a35a" : "#dc2626";
    ctx.beginPath();
    ctx.moveTo(xx, y(candle.high));
    ctx.lineTo(xx, y(candle.low));
    ctx.stroke();
    const top = y(Math.max(candle.open, candle.close));
    const bottom = y(Math.min(candle.open, candle.close));
    ctx.fillRect(xx - candleW / 2, top, candleW, Math.max(2, bottom - top));
  });

  const pattern = result.patterns[0];
  if (pattern) {
    ctx.strokeStyle = "#2563eb";
    ctx.setLineDash([5, 4]);
    ctx.beginPath();
    ctx.moveTo(pad.left, y(pattern.level));
    ctx.lineTo(width - pad.right, y(pattern.level));
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#174ea6";
    ctx.fillText(`${pattern.label} ${pattern.level.toFixed(2)}`, pad.left + 8, y(pattern.level) - 7);
  }

  const maxVolume = Math.max(1, ...candles.map((item) => item.volume));
  candles.forEach((candle, idx) => {
    const barH = candle.volume / maxVolume * 34;
    ctx.fillStyle = candle.close >= candle.open ? "rgba(21,128,61,.28)" : "rgba(185,28,28,.28)";
    ctx.fillRect(x(idx) - candleW / 2, height - pad.bottom + 36 - barH, candleW, barH);
  });

  ctx.fillStyle = "#0f172a";
  ctx.font = "13px Arial";
  ctx.fillText(`${result.symbol} ${result.last_price.toFixed(2)} | ${result.market_phase}`, pad.left, 18);
}

function decisionRow(title, label, detail, tone) {
  return `<article class="decision-item" data-tone="${tone}">
    <span>${escapeHtml(title)}</span>
    <strong>${escapeHtml(label)}</strong>
    <p>${escapeHtml(detail)}</p>
  </article>`;
}

function renderDecisionSummary(result) {
  const summary = result.decision_summary || {};
  if (!summary.technical) {
    elements.decisionSummary.innerHTML = '<p class="decision-empty">ยังไม่มีสรุปการตัดสินใจของหุ้นตัวนี้</p>';
    return;
  }
  const freshness = result.price_is_fresh
    ? ""
    : `<p class="decision-alert">ราคาล่าสุดของหุ้นตัวนี้คือ ${escapeHtml(result.price_as_of)} ซึ่งไม่ใช่วัน EOD ที่ใช้สแกน</p>`;
  elements.decisionSummary.innerHTML = `${freshness}
    <div class="decision-grid">
      ${decisionRow("Technical", summary.technical.label, summary.technical.detail, summary.technical.pass ? "ok" : "bad")}
      ${decisionRow("งบการเงิน", summary.financials.label, summary.financials.detail, summary.financials.verified ? "ok" : "warn")}
      ${decisionRow("มูลค่า", summary.valuation.label, summary.valuation.detail, summary.valuation.verified ? "ok" : "warn")}
      ${decisionRow("ความเสี่ยง", summary.risk.label, summary.risk.detail, "neutral")}
    </div>
    <p class="decision-footer">สถานะงานวิจัย <b>${escapeHtml(summary.research_status || "Watch")}</b>${summary.thesis ? ` · ${escapeHtml(summary.thesis)}` : ""}</p>`;
}

function renderDetail(payload) {
  const { result, candles, fundamental, tradingview_url } = payload;
  elements.detailTitle.closest(".detail-panel").dataset.state = "ready";
  state.selectedSymbol = result.symbol;
  state.detailPayload = payload;
  document.querySelectorAll("tbody tr").forEach((row) => {
    row.classList.toggle("active", row.dataset.symbol === result.symbol);
  });
  elements.detailTitle.textContent = `${result.symbol} - ${result.name}`;
  elements.detailSubtitle.textContent = `${result.market} | ${result.sector} | TF ${result.timeframe} | ${result.decision}`;
  elements.detailGrade.textContent = result.grade;
  renderDecisionSummary(result);
  drawChart(aggregateCandles(candles, elements.timeframeSelect.value), result);
  elements.tradingViewButton.href = tradingview_url;
  elements.reportButton.href = `/api/report?symbol=${encodeURIComponent(result.symbol)}&${state.criteriaQuery}`;
  loadResearch(result.symbol);

  renderDefinitionList(elements.riskPlan, [
    ["Bias", result.risk_plan.bias],
    ["Entry", result.risk_plan.entry.toFixed(2)],
    ["Stop", result.risk_plan.stop.toFixed(2)],
    ["Targets", result.risk_plan.targets.map((item) => item.toFixed(2)).join(", ")],
    ["R:R", `${result.risk_plan.reward_risk.toFixed(2)}R`],
  ]);

  renderDefinitionList(elements.fundamentalBox, fundamental.fundamentals_verified ? [
    ["Status", `Verified (${fundamental.as_of || "latest annual"})`],
    ["ROE / ROA", `${fundamental.roe.toFixed(1)}% / ${fundamental.roa.toFixed(1)}%`],
    ["Debt", `${fundamental.debt_to_equity.toFixed(2)}x`],
    ["Growth", `${fundamental.revenue_growth.toFixed(1)}% / ${fundamental.profit_growth.toFixed(1)}%`],
  ] : [
    ["Status", "รอตรวจงบการเงิน"],
    ["Next step", "เปิดแท็บงบการเงินเพื่อยืนยันข้อมูล"],
  ]);

  elements.agentNotes.innerHTML = "";
  result.insights.forEach((insight) => {
    const box = document.createElement("article");
    box.className = "agent-item";
    box.innerHTML = `
      <strong>${insight.agent} (${insight.score.toFixed(1)})</strong>
      <p>${insight.summary}</p>
      <ul>${insight.bullets.map((item) => `<li>${item}</li>`).join("")}</ul>
    `;
    elements.agentNotes.appendChild(box);
  });

  elements.warningList.innerHTML = result.warnings.length
    ? result.warnings.map((item) => `<li>${item}</li>`).join("")
    : "<li>No major warning from scanner</li>";
}

async function loadSymbol(symbol, { select = true } = {}) {
  const requestId = ++state.symbolRequestId;
  if (select) {
    window.fastDeepSelectedSymbol = symbol;
    window.dispatchEvent(new CustomEvent("fastdeep:symbol-selected", {
      detail: { symbol, source: "scanner" },
    }));
  }
  setStatus("Loading");
  try {
    const response = await fetch(`/api/symbol?symbol=${encodeURIComponent(symbol)}&${state.criteriaQuery}`);
    const payload = await response.json();
    if (requestId !== state.symbolRequestId || window.fastDeepSelectedSymbol !== symbol) return;
    if (!response.ok) throw new Error(payload.error || "โหลดหุ้นไม่สำเร็จ");
    renderDetail(payload);
    setStatus("Ready");
  } catch (error) {
    if (requestId === state.symbolRequestId) setStatus("Symbol error");
  }
}

async function savePaperTrade() {
  const result = state.results.find((item) => item.symbol === state.selectedSymbol);
  if (!result) return;
  elements.paperTradeButton.disabled = true;
  try {
    const response = await fetch("/api/trades", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        symbol: result.symbol,
        entry: result.risk_plan.entry,
        stop: result.risk_plan.stop,
        targets: result.risk_plan.targets,
        side: result.patterns.some((item) => item.side === "SELL") ? "SELL" : "BUY",
        timeframe: result.timeframe,
        pattern: result.patterns[0] ? result.patterns[0].name : "",
        grade: result.grade,
        currency: result.currency,
        note: result.decision,
      }),
    });
    const item = await response.json();
    if (!response.ok) throw new Error(item.error || "บันทึก Paper Trade ไม่ได้");
    elements.paperTradeStatus.textContent = `บันทึกแล้ว: ${item.trade.symbol} เข้า ${item.trade.entry} ตัดขาดทุน ${item.trade.stop}`;
    loadJournal();
  } catch (error) {
    elements.paperTradeStatus.textContent = error.message;
  } finally {
    elements.paperTradeButton.disabled = false;
  }
}

function horizonCell(stats, edge) {
  if (!stats) return "<td>-</td>";
  const edgeText = edge ? `${edge.return_edge_pp > 0 ? "+" : ""}${edge.return_edge_pp} pp` : "-";
  const tone = edge && edge.return_edge_pp > 0 ? "ok" : "bad";
  return `<td data-tone="${tone}">
    <strong>${stats.average_return_pct_net}%</strong>
    <small>ชนะ ${stats.hit_rate_pct}% · ย่อเฉลี่ย ${stats.average_max_drawdown_pct}%</small>
    <small>ส่วนต่างจากค่าฐาน ${edgeText}</small>
  </td>`;
}

async function loadEvidence() {
  const timeframe = elements.evidenceTimeframe.value;
  elements.evidenceBody.innerHTML = "<tr><td>กำลังโหลด...</td></tr>";
  const response = await fetch(`/api/event-study?timeframe=${encodeURIComponent(timeframe)}`);
  const payload = await response.json();
  if (!response.ok) {
    elements.evidenceMethod.textContent = payload.error || "โหลดผลย้อนหลังไม่สำเร็จ";
    elements.evidenceHead.innerHTML = "";
    elements.evidenceBody.innerHTML = "";
    return;
  }
  const horizons = payload.horizons || [];
  elements.evidenceMethod.textContent = `${payload.method} | หุ้น ${payload.symbols_scanned} ตัว · สัญญาณ ${payload.signals} ครั้ง · ค่าคอมมิชชันและ slippage ${payload.cost_bps} bps`;
  elements.evidenceSubtitle.textContent = "ตัวเลขคือผลตอบแทนเฉลี่ยสุทธิหลังสัญญาณ เทียบกับการเข้าซื้อแบบสุ่มในหุ้นชุดเดียวกัน (ค่าฐาน)";
  elements.evidenceHead.innerHTML = `<tr><th>Pattern</th><th>จำนวนสัญญาณ</th>${horizons.map((value) => `<th>ถือ ${value} แท่ง</th>`).join("")}</tr>`;
  const baselineRow = `<tr class="baseline-row"><th>ค่าฐาน (เข้าซื้อแบบสุ่ม)</th><td>${payload.baseline.signals}</td>${horizons.map((value) => {
    const stats = payload.baseline[`h${value}`];
    return stats ? `<td><strong>${stats.average_return_pct_net}%</strong><small>ชนะ ${stats.hit_rate_pct}%</small></td>` : "<td>-</td>";
  }).join("")}</tr>`;
  const rows = (payload.by_pattern || []).map((row) => `<tr>
    <th>${escapeHtml(row.pattern)}${row.reliable ? "" : " *"}</th>
    <td>${row.signals}</td>
    ${horizons.map((value) => horizonCell(row[`h${value}`], (row.edge_vs_baseline || {})[`h${value}`])).join("")}
  </tr>`).join("");
  elements.evidenceBody.innerHTML = baselineRow + rows;
}

async function loadJournal() {
  const response = await fetch("/api/trades");
  if (!response.ok) return;
  const payload = await response.json();
  const summary = payload.summary || {};
  elements.journalScore.textContent = summary.hit_rate_pct === null || summary.hit_rate_pct === undefined
    ? "-"
    : `${summary.hit_rate_pct}%`;
  elements.journalKpis.innerHTML = [
    ["ไม้ที่ยังเปิดอยู่", summary.open_count ?? 0, "รายการ"],
    ["ไม้ที่ปิดแล้ว", summary.closed_count ?? 0, "รายการ"],
    ["ผลตอบแทนเฉลี่ยสุทธิ", summary.average_return_pct_net === null || summary.average_return_pct_net === undefined ? "-" : `${summary.average_return_pct_net}%`, `หักต้นทุน ${summary.cost_bps} bps`],
    ["ค่าเฉลี่ย R", summary.average_r ?? "-", "กำไรต่อความเสี่ยง 1 หน่วย"],
  ].map(([label, value, note]) => (
    `<article class="financial-kpi"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong><small>${escapeHtml(note)}</small></article>`
  )).join("");
  elements.journalBody.innerHTML = (payload.trades || []).map((trade) => `<tr>
    <th>${escapeHtml(trade.symbol)}<small>${escapeHtml(trade.pattern || "-")} · ${escapeHtml(trade.timeframe)}</small></th>
    <td>${escapeHtml(trade.state)}</td>
    <td>${trade.entry}</td>
    <td>${trade.stop}</td>
    <td>${trade.exit ?? "-"}</td>
    <td>${trade.return_pct_net === null || trade.return_pct_net === undefined ? "-" : `${trade.return_pct_net}%`}</td>
    <td>${trade.r_multiple ?? "-"}</td>
    <td>${escapeHtml(trade.opened_on)}</td>
    <td>${trade.state === "open" ? `<button class="ghost-button close-trade" type="button" data-id="${escapeHtml(trade.id)}">ปิดไม้</button>` : ""}</td>
  </tr>`).join("");
}

async function closeTrade(id) {
  const value = window.prompt("ราคาปิดของไม้นี้");
  if (!value) return;
  const response = await fetch("/api/trades/close", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, exit_price: value }),
  });
  const payload = await response.json();
  if (!response.ok) {
    window.alert(payload.error || "ปิดไม้ไม่สำเร็จ");
    return;
  }
  loadJournal();
}

async function runScan() {
  if (window.fastDeepUniverse?.ready) await window.fastDeepUniverse.ready;
  const requestId = ++state.scanRequestId;
  state.symbolRequestId += 1;
  state.detailPayload = null;
  state.results = [];
  const selectedAtStart = window.fastDeepSelectedSymbol;
  setStatus("Scanning");
  elements.detailTitle.closest(".detail-panel").dataset.state = "empty";
  elements.detailTitle.textContent = "กำลังสแกนกลุ่มที่เลือก";
  elements.detailSubtitle.textContent = "";
  elements.detailGrade.textContent = "-";
  elements.resultsBody.innerHTML = '<tr><td colspan="6" class="empty-row">กำลังสแกน...</td></tr>';
  for (const element of [elements.metricCount, elements.metricBest, elements.metricA, elements.metricMarket]) element.textContent = "...";
  const query = criteriaQuery();
  elements.csvButton.href = `/api/export.csv?${query}`;
  try {
    const response = await fetch(`/api/scan?${query}`);
    const payload = await response.json();
    if (requestId !== state.scanRequestId) return;
    if (!response.ok) throw new Error(payload.error || "สแกนไม่สำเร็จ");
    elements.dataSourceNote.textContent = `Data Source: ${payload.data_source || "unknown"}`;
    renderDataHealth(payload.data_health, payload.financial_health, payload);
    state.results = payload.results;
    renderMetrics(payload.results);
    renderTable(payload.results);
    window.fastDeepUniverse?.refresh();
    const generatedAt = payload.generated_at ? new Date(payload.generated_at).toLocaleString() : "-";
    const shown = Math.min(payload.results.length, MAX_VISIBLE_RESULTS);
    elements.generatedAt.textContent = `${generatedAt} | แสดง ${shown}/${payload.results.length}`;
    setStatus("Ready");
    elements.detailTitle.textContent = "เลือกหุ้นจากผลสแกน";
    if (payload.results.length && window.fastDeepSelectedSymbol === selectedAtStart
        && !document.getElementById("scannerView").classList.contains("is-hidden")) {
      const preferred = payload.results.find((item) => item.symbol === selectedAtStart) || payload.results[0];
      await loadSymbol(preferred.symbol);
    }
  } catch (error) {
    if (requestId === state.scanRequestId) {
      state.results = [];
      renderMetrics([]);
      elements.resultsBody.innerHTML = '<tr><td colspan="6" class="empty-row">สแกนไม่สำเร็จ กรุณาลองอีกครั้ง</td></tr>';
      elements.detailTitle.textContent = "ยังไม่มีผลสแกน";
      setStatus("Scan error");
    }
  }
}

elements.scoreRange.addEventListener("input", () => {
  elements.scoreValue.textContent = elements.scoreRange.value;
});
elements.scanButton.addEventListener("click", runScan);
elements.paperTradeButton.addEventListener("click", savePaperTrade);
elements.evidenceTimeframe.addEventListener("change", loadEvidence);
elements.journalBody.addEventListener("click", (event) => {
  const button = event.target.closest(".close-trade");
  if (button) closeTrade(button.dataset.id);
});
document.querySelectorAll('[data-view-target="evidenceView"]').forEach((tab) => {
  tab.addEventListener("click", loadEvidence);
});
document.querySelectorAll('[data-view-target="journalView"]').forEach((tab) => {
  tab.addEventListener("click", loadJournal);
});
elements.researchSaveButton.addEventListener("click", saveResearch);
window.addEventListener("fastdeep:financials-verified", (event) => {
  const symbol = event.detail?.symbol;
  if (symbol && symbol === state.selectedSymbol && symbol === window.fastDeepSelectedSymbol) loadSymbol(symbol, { select: false });
});
window.addEventListener("fastdeep:symbol-selected", (event) => {
  if (event.detail?.source !== "scanner") state.symbolRequestId += 1;
});
elements.marketSelect.addEventListener("change", runScan);
elements.universeSelect.addEventListener("change", runScan);
elements.timeframeSelect.addEventListener("change", runScan);
function showChartFile(file) {
  if (!file || !file.type.startsWith("image/")) {
    elements.imageMatches.innerHTML = "<p>กรุณาเลือกไฟล์รูปภาพ</p>";
    return;
  }
  elements.chartImagePreview.src = URL.createObjectURL(file);
  elements.chartDropZone.classList.add("has-image");
  elements.chartFileName.textContent = file.name;
  elements.imageMatches.innerHTML = "<p>พร้อมแล้ว กดค้นหาหุ้นที่ทรงกราฟคล้ายกัน</p>";
}

elements.chartImageInput.addEventListener("change", () => {
  showChartFile(elements.chartImageInput.files && elements.chartImageInput.files[0]);
});

for (const eventName of ["dragenter", "dragover"]) {
  elements.chartDropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.chartDropZone.classList.add("is-dragging");
  });
}
for (const eventName of ["dragleave", "drop"]) {
  elements.chartDropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.chartDropZone.classList.remove("is-dragging");
  });
}
elements.chartDropZone.addEventListener("drop", (event) => {
  const file = event.dataTransfer?.files?.[0];
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  elements.chartImageInput.files = transfer.files;
  showChartFile(file);
});

elements.imageMatches.addEventListener("click", (event) => {
  const button = event.target.closest(".image-profile-button");
  if (!button) return;
  const symbol = button.dataset.symbol;
  window.fastDeepSelectedSymbol = symbol;
  window.dispatchEvent(new CustomEvent("fastdeep:symbol-selected", { detail: { symbol, source: "image-match" } }));
  const profileTab = document.querySelector('[data-view-target="profileView"]');
  if (profileTab) profileTab.click();
});
elements.imageScanButton.addEventListener("click", async () => {
  const file = elements.chartImageInput.files && elements.chartImageInput.files[0];
  if (!file) {
    elements.imageMatches.innerHTML = "<p>กรุณาแนบรูปกราฟก่อน</p>";
    return;
  }
  if (state.dataHealth && !state.dataHealth.can_publish) {
    elements.imageMatches.innerHTML = `<p>${state.dataHealth.message}</p>`;
    return;
  }
  elements.imageMatches.innerHTML = "<p>กำลังอ่านรูปและเทียบทรงกราฟ...</p>";
  setStatus("Image scan");
  try {
    const shape = await extractImageShape(file);
    const indexRows = await loadImageIndex();
    renderImageMatches(scanImageMatches(shape, indexRows));
    setStatus("Ready");
  } catch (error) {
    elements.imageMatches.innerHTML = `<p>${error.message}</p>`;
    setStatus("Image error");
  }
});
document.querySelectorAll(".pattern-controls input").forEach((input) => {
  input.addEventListener("change", runScan);
});

window.addEventListener("resize", () => {
  if (state.detailPayload && !document.getElementById("scannerView").classList.contains("is-hidden")) {
    drawChart(aggregateCandles(state.detailPayload.candles, elements.timeframeSelect.value), state.detailPayload.result);
  }
});

runScan();
