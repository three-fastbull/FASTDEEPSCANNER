const state = {
  results: [],
  selectedSymbol: null,
  criteriaQuery: "",
  imageIndex: null,
  dataHealth: null,
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
  imageScanButton: document.getElementById("imageScanButton"),
  chartImagePreview: document.getElementById("chartImagePreview"),
  imageMatches: document.getElementById("imageMatches"),
  dataHealth: document.getElementById("dataHealth"),
  researchStatus: document.getElementById("researchStatus"),
  researchNote: document.getElementById("researchNote"),
  researchSaveButton: document.getElementById("researchSaveButton"),
  researchSavedAt: document.getElementById("researchSavedAt"),
};

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
        <a class="ghost-button" href="${match.tradingview_url}" target="_blank" rel="noreferrer">TV</a>
      </article>
    `;
  }).join("");
}

function setStatus(text) {
  elements.scanStatus.textContent = text;
}

function renderDataHealth(health, financialHealth = null) {
  state.dataHealth = health || null;
  if (!health) return;
  const latest = health.latest_candle_date || "-";
  const scannerAsOf = health.scanner_as_of_date || latest;
  const coverage = health.symbols_requested
    ? `${health.symbols_succeeded}/${health.symbols_requested}`
    : "-";
  const financialCoverage = financialHealth
    ? ` | งบยืนยัน ${financialHealth.fresh_symbols}/${financialHealth.symbols_requested}`
    : "";
  elements.dataHealth.textContent = `${health.message} | EOD ที่ใช้สแกน ${scannerAsOf} | Feed ล่าสุด ${latest} | Coverage ${coverage}${financialCoverage}`;
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
      }),
    });
    const item = await response.json();
    if (!response.ok) throw new Error(item.error || "บันทึกสถานะไม่ได้");
    elements.researchSavedAt.textContent = `บันทึก ${new Date(item.updated_at).toLocaleString("th-TH")}`;
  } catch (error) {
    elements.researchSavedAt.textContent = error.message || "บันทึกสถานะไม่ได้";
  } finally {
    elements.researchSaveButton.disabled = false;
  }
}

function scoreClass(decision) {
  if (decision.includes("Candidate") || decision.includes("Watchlist")) return "good";
  if (decision.includes("Reject")) return "bad";
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
  for (const result of results.slice(0, MAX_VISIBLE_RESULTS)) {
    const topPattern = result.patterns[0];
    const row = document.createElement("tr");
    row.dataset.symbol = result.symbol;
    row.innerHTML = `
      <td class="symbol-cell"><strong>${result.symbol}</strong><span>${result.name}</span></td>
      <td><span class="pattern-chip">${topPattern ? topPattern.label : "-"}</span></td>
      <td><strong>${result.grade}</strong></td>
      <td>${result.final_score.toFixed(1)}</td>
      <td>${result.fundamentals_verified ? result.fundamental_score.toFixed(1) : "รอตรวจ"}</td>
      <td class="decision ${scoreClass(result.decision)}">${result.decision}</td>
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
  canvas.width = Math.max(640, Math.floor(rect.width * dpr));
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

  const candleW = Math.max(3, chartW / candles.length * 0.58);
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

  const maxVolume = Math.max(...candles.map((item) => item.volume));
  candles.forEach((candle, idx) => {
    const barH = candle.volume / maxVolume * 34;
    ctx.fillStyle = candle.close >= candle.open ? "rgba(21,128,61,.28)" : "rgba(185,28,28,.28)";
    ctx.fillRect(x(idx) - candleW / 2, height - pad.bottom + 36 - barH, candleW, barH);
  });

  ctx.fillStyle = "#0f172a";
  ctx.font = "13px Arial";
  ctx.fillText(`${result.symbol} ${result.last_price.toFixed(2)} | ${result.market_phase}`, pad.left, 18);
}

function renderDetail(payload) {
  const { result, candles, fundamental, tradingview_url } = payload;
  state.selectedSymbol = result.symbol;
  window.fastDeepSelectedSymbol = result.symbol;
  window.dispatchEvent(new CustomEvent("fastdeep:symbol-selected", {
    detail: {
      symbol: result.symbol,
      name: result.name,
      market: result.market,
      source: "scanner",
    },
  }));
  document.querySelectorAll("tbody tr").forEach((row) => {
    row.classList.toggle("active", row.dataset.symbol === result.symbol);
  });
  elements.detailTitle.textContent = `${result.symbol} - ${result.name}`;
  elements.detailSubtitle.textContent = `${result.market} | ${result.sector} | TF ${result.timeframe} | ${result.decision}`;
  elements.detailGrade.textContent = result.grade;
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

async function loadSymbol(symbol) {
  setStatus("Loading");
  const response = await fetch(`/api/symbol?symbol=${encodeURIComponent(symbol)}&${state.criteriaQuery}`);
  if (!response.ok) {
    setStatus("Symbol error");
    return;
  }
  renderDetail(await response.json());
  setStatus("Ready");
}

async function runScan() {
  setStatus("Scanning");
  const query = criteriaQuery();
  elements.csvButton.href = `/api/export.csv?${query}`;
  const response = await fetch(`/api/scan?${query}`);
  if (!response.ok) {
    setStatus("Scan error");
    return;
  }
  const payload = await response.json();
  elements.dataSourceNote.textContent = `Data Source: ${payload.data_source || "unknown"}`;
  renderDataHealth(payload.data_health, payload.financial_health);
  state.results = payload.results;
  renderMetrics(payload.results);
  renderTable(payload.results);
  const generatedAt = payload.generated_at ? new Date(payload.generated_at).toLocaleString() : "-";
  const shown = Math.min(payload.results.length, MAX_VISIBLE_RESULTS);
  elements.generatedAt.textContent = `${generatedAt} | แสดง ${shown}/${payload.results.length}`;
  setStatus("Ready");
  if (payload.results.length) {
    await loadSymbol(payload.results[0].symbol);
  }
}

elements.scoreRange.addEventListener("input", () => {
  elements.scoreValue.textContent = elements.scoreRange.value;
});
elements.scanButton.addEventListener("click", runScan);
elements.researchSaveButton.addEventListener("click", saveResearch);
window.addEventListener("fastdeep:financials-verified", (event) => {
  const symbol = event.detail?.symbol;
  if (symbol && symbol === state.selectedSymbol) loadSymbol(symbol);
});
elements.marketSelect.addEventListener("change", runScan);
elements.universeSelect.addEventListener("change", runScan);
elements.timeframeSelect.addEventListener("change", runScan);
elements.chartImageInput.addEventListener("change", () => {
  const file = elements.chartImageInput.files && elements.chartImageInput.files[0];
  if (!file) return;
  elements.chartImagePreview.src = URL.createObjectURL(file);
  elements.imageMatches.innerHTML = "<p>แนบรูปแล้ว กด Scan รูปกราฟ</p>";
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
  if (state.selectedSymbol) loadSymbol(state.selectedSymbol);
});

runScan();
