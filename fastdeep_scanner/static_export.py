from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .data_io import data_source_label, load_market_data
from .models import ScanCriteria
from .scanner import scan_market


def build_static_dashboard_html(criteria: ScanCriteria | None = None) -> str:
    criteria = criteria or ScanCriteria()
    candles_by_symbol, fundamentals = load_market_data()
    results = scan_market(criteria)
    result_symbols = {result.symbol for result in results}
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "data_source": data_source_label(),
        "results": [result.to_dict() for result in results],
        "symbols": {
            symbol: {
                "candles": [candle.to_dict() for candle in candles[-180:]],
                "fundamental": fundamentals[symbol].to_dict(),
            }
            for symbol, candles in candles_by_symbol.items()
            if symbol in fundamentals and symbol in result_symbols
        },
        "image_index": [
            {
                "symbol": symbol,
                "name": fundamentals[symbol].name if symbol in fundamentals else symbol,
                "market": fundamentals[symbol].market if symbol in fundamentals else "US",
                "sector": fundamentals[symbol].sector if symbol in fundamentals else "Unknown",
                "index_groups": fundamentals[symbol].index_groups if symbol in fundamentals else "",
                "series": [
                    {"date": candle.date.isoformat(), "close": round(candle.close, 6)}
                    for candle in candles[-180:]
                ],
            }
            for symbol, candles in candles_by_symbol.items()
            if symbol in fundamentals
        ],
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    html = """<!doctype html>
<html lang="th">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FastDeep Scanner</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Arial, sans-serif; background: #f5f7fb; color: #0f172a; }
    header { min-height: 78px; padding: 18px 24px; background: #fff; border-bottom: 1px solid #dbe3ee; display: flex; justify-content: space-between; gap: 16px; align-items: center; }
    h1 { margin: 0; font-size: 28px; }
    h2 { margin: 0 0 10px; font-size: 18px; }
    h3 { margin: 0 0 8px; font-size: 15px; }
    p { margin: 0; color: #64748b; }
    main { padding: 16px 24px 28px; }
    .controls { display: grid; grid-template-columns: minmax(180px, 1fr) 145px 110px 110px 170px 1.4fr auto auto; gap: 12px; align-items: end; padding: 14px; background: #fff; border: 1px solid #dbe3ee; border-radius: 8px; }
    label { display: grid; gap: 6px; color: #64748b; font-size: 12px; font-weight: 700; }
    input[type="search"], select { min-height: 38px; padding: 0 10px; border: 1px solid #dbe3ee; border-radius: 6px; background: #fff; color: #0f172a; }
    input[type="range"] { width: 100%; }
    .patterns { display: flex; flex-wrap: wrap; gap: 8px; }
    .patterns label { grid-auto-flow: column; align-items: center; gap: 6px; min-height: 34px; padding: 6px 9px; border: 1px solid #dbe3ee; border-radius: 6px; background: #fbfcfe; color: #0f172a; }
    button { min-height: 38px; padding: 0 15px; border: 0; border-radius: 6px; font-weight: 700; cursor: pointer; }
    .primary { background: #2563eb; color: #fff; }
    .secondary { background: #fff; color: #0f172a; border: 1px solid #dbe3ee; }
    .metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 14px 0; }
    .metric, section { background: #fff; border: 1px solid #dbe3ee; border-radius: 8px; }
    .metric { min-height: 70px; padding: 12px 14px; }
    .metric span { display: block; color: #64748b; font-size: 12px; font-weight: 700; }
    .metric strong { display: block; margin-top: 6px; font-size: 24px; }
    .workspace { display: grid; grid-template-columns: minmax(520px, .95fr) minmax(460px, 1.05fr); gap: 14px; align-items: start; }
    .head { min-height: 58px; padding: 14px; border-bottom: 1px solid #dbe3ee; display: flex; justify-content: space-between; gap: 12px; align-items: center; }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; min-width: 720px; border-collapse: collapse; }
    th, td { padding: 11px 14px; border-bottom: 1px solid #e8edf4; text-align: left; vertical-align: top; font-size: 13px; }
    th { color: #64748b; font-size: 12px; }
    tr { cursor: pointer; }
    tr:hover, tr.active { background: #eef6ff; }
    .symbol strong { display: block; }
    .symbol span { color: #64748b; font-size: 12px; }
    .badge { display: inline-block; padding: 5px 9px; border-radius: 6px; background: #e8f1ff; color: #174ea6; font-weight: 700; }
    .chip { display: inline-block; padding: 4px 8px; border-radius: 6px; background: #ecfdf5; color: #15803d; font-weight: 700; }
    .good { color: #15803d; font-weight: 700; }
    .bad { color: #b91c1c; font-weight: 700; }
    .warn { color: #b45309; font-weight: 700; }
    .source-note { margin-top: 10px; padding: 10px 12px; border: 1px solid #f3d38a; border-radius: 8px; background: #fff7df; color: #7c4a03; font-size: 13px; font-weight: 700; }
    .disclaimer { margin: 0 0 18px; padding: 12px 14px; border: 1px solid #f0b8b8; border-left: 4px solid #c5352f; border-radius: 8px; background: #fdf3f2; color: #7d211d; font-size: 13px; line-height: 1.7; }
    .disclaimer strong { display: block; margin-bottom: 4px; font-size: 14px; }
    canvas { width: calc(100% - 28px); height: 320px; margin: 14px; border: 1px solid #dbe3ee; border-radius: 8px; background: #fbfcfe; }
    .detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 0 14px 14px; }
    .box { border-top: 1px solid #dbe3ee; padding-top: 14px; }
    dl { display: grid; grid-template-columns: 112px 1fr; gap: 8px; margin: 0; font-size: 13px; }
    dt { color: #64748b; font-weight: 700; }
    dd { margin: 0; }
    .agents { padding: 0 14px 14px; display: grid; gap: 8px; }
    .agent { border: 1px solid #dbe3ee; border-radius: 8px; padding: 10px; background: #fbfcfe; }
    .agent strong { display: block; margin-bottom: 4px; }
    .actions { display: flex; gap: 10px; padding: 0 14px 14px; }
    .link-button { display: inline-flex; min-height: 38px; align-items: center; justify-content: center; padding: 0 14px; border-radius: 6px; background: #fff; border: 1px solid #dbe3ee; color: #0f172a; text-decoration: none; font-weight: 700; }
    .image-band { margin: 14px 0; padding: 14px; background: #fff; border: 1px solid #dbe3ee; border-radius: 8px; display: grid; grid-template-columns: minmax(260px, .72fr) minmax(280px, 1.28fr); gap: 14px; align-items: start; }
    .image-tools { display: grid; gap: 10px; }
    .file-input { min-height: 40px; padding: 8px; border: 1px solid #dbe3ee; border-radius: 6px; background: #fbfcfe; }
    .preview-wrap { display: grid; grid-template-columns: 160px 1fr; gap: 12px; align-items: start; }
    #imagePreview { width: 160px; min-height: 105px; border: 1px solid #dbe3ee; border-radius: 8px; object-fit: contain; background: #f8fafc; }
    .matches { display: grid; gap: 8px; }
    .match-item { display: grid; grid-template-columns: 72px 1fr auto; gap: 10px; align-items: center; padding: 10px; border: 1px solid #dbe3ee; border-radius: 8px; background: #fbfcfe; }
    .match-score { font-weight: 800; color: #174ea6; }
    .empty { padding: 28px; color: #64748b; text-align: center; }
    @media (max-width: 1180px) {
      .controls, .workspace { grid-template-columns: 1fr; }
      .metrics { grid-template-columns: repeat(2, 1fr); }
    }
    @media (max-width: 680px) {
      header, main { padding-left: 14px; padding-right: 14px; }
      h1 { font-size: 22px; }
      .metrics, .detail-grid { grid-template-columns: 1fr; }
      .patterns { flex-direction: column; }
      .image-band, .preview-wrap { grid-template-columns: 1fr; }
      button { width: 100%; }
    }
  </style>
</head>
<body>
  <header>
      <div>
        <p>FastDeep Intelligence Platform</p>
        <h1>Scanner หุ้น</h1>
        <div class="source-note" id="dataSourceNote">Data Source: loading...</div>
      </div>
    <span class="badge" id="statusBadge">พร้อมสแกน</span>
  </header>

  <!-- The export carries entry, stop and target levels, which read like trade
       calls once the file leaves this machine. The banner travels with them. -->
  <p class="disclaimer">
    <strong>ใช้เพื่อการศึกษาเท่านั้น ไม่ใช่คำแนะนำการลงทุน</strong>
    รายชื่อและระดับราคาในหน้านี้เป็นผลจากการคำนวณอัตโนมัติ ไม่ใช่สัญญาณซื้อขาย
    และไม่ได้ผ่านการวิเคราะห์ธุรกิจโดยคน โปรดตรวจสอบข้อมูลจากแหล่งทางการก่อนตัดสินใจทุกครั้ง
    การลงทุนมีความเสี่ยง ผู้ลงทุนรับผิดชอบการตัดสินใจของตนเอง
    <span id="snapshotNote"></span>
  </p>

  <main>
    <div class="controls">
      <label>ค้นหาหุ้น
        <input id="searchBox" type="search" placeholder="เช่น ADVANC, NVDA, AOT">
      </label>
      <label>ตลาด
        <select id="marketSelect">
          <option value="ALL">ALL</option>
          <option value="TH">TH</option>
          <option value="US">US</option>
          <option value="CN">CN</option>
          <option value="HK">HK</option>
        </select>
      </label>
      <label>Universe
        <select id="universeSelect">
          <option value="ALL">ALL</option>
          <option value="SP500">S&P 500</option>
          <option value="NASDAQ100">Nasdaq-100</option>
          <option value="SP400">S&amp;P MidCap 400</option>
          <option value="CSI300">CSI 300</option>
          <option value="HSI">Hang Seng Index</option>
          <option value="HSTECH">Hang Seng Tech</option>
          <option value="CHINA50">China 50</option>
          <option value="SET_SAMPLE">หุ้นไทย</option>
          <option value="SET50">SET50</option>
          <option value="SET100">SET100</option>
          <option value="MAI">MAI</option>
        </select>
      </label>
      <label>Timeframe
        <select id="timeframeSelect">
          <option value="D">D</option>
          <option value="W">W</option>
          <option value="M">M</option>
        </select>
      </label>
      <label>คะแนนขั้นต่ำ <span id="scoreText">55</span>
        <input id="scoreRange" type="range" min="45" max="95" value="55">
      </label>
      <div class="patterns" id="patternBox">
        <label><input type="checkbox" value="breakout" checked> Breakout</label>
        <label><input type="checkbox" value="retest" checked> Retest</label>
        <label><input type="checkbox" value="cup_handle" checked> Cup & Handle</label>
        <label><input type="checkbox" value="double_bottom" checked> Double Bottom</label>
        <label><input type="checkbox" value="head_shoulders" checked> Head & Shoulders</label>
      </div>
      <button class="primary" id="scanButton">Scan</button>
      <button class="secondary" id="resetButton">Reset</button>
    </div>

    <div class="metrics">
      <div class="metric"><span>พบหุ้น</span><strong id="metricCount">0</strong></div>
      <div class="metric"><span>คะแนนสูงสุด</span><strong id="metricBest">0</strong></div>
      <div class="metric"><span>A / A+</span><strong id="metricA">0</strong></div>
      <div class="metric"><span>TF ที่สแกน</span><strong id="metricTimeframe">D</strong></div>
    </div>

    <section class="image-band">
      <div class="image-tools">
        <div>
          <h2>Image Match</h2>
          <p>แนบรูปกราฟ แล้วสแกนหา asset ที่ทรงกราฟคล้ายกันใน universe</p>
        </div>
        <input class="file-input" id="chartImageInput" type="file" accept="image/*">
        <button class="primary" id="imageScanButton">Scan รูปกราฟ</button>
      </div>
      <div class="preview-wrap">
        <img id="imagePreview" alt="Chart image preview">
        <div>
          <h3>ผลลัพธ์รูปที่คล้าย</h3>
          <div class="matches" id="imageMatches">
            <p>ยังไม่ได้แนบรูป</p>
          </div>
        </div>
      </div>
    </section>

    <div class="workspace">
      <section>
        <div class="head">
          <div>
            <h2>ผลสแกน</h2>
            <p id="generatedAt"></p>
          </div>
          <span class="badge" id="rowCount">0</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>หุ้น</th><th>Pattern</th><th>Grade</th><th>Score</th><th>พื้นฐาน</th><th>Decision</th></tr>
            </thead>
            <tbody id="rows"></tbody>
          </table>
        </div>
      </section>

      <section>
        <div class="head">
          <div>
            <h2 id="title">เลือกหุ้นจากผลสแกน</h2>
            <p id="subtitle"></p>
          </div>
          <span class="badge" id="gradeBadge">-</span>
        </div>
        <canvas id="chart" width="760" height="320"></canvas>
        <div class="actions">
          <a class="link-button" id="tradingViewLink" href="#" target="_blank" rel="noreferrer">เปิด TradingView</a>
        </div>
        <div class="detail-grid">
          <div class="box"><h3>Risk Plan</h3><dl id="risk"></dl></div>
          <div class="box"><h3>Fundamental</h3><dl id="fundamental"></dl></div>
        </div>
        <div class="agents" id="agents"></div>
      </section>
    </div>
  </main>

  <script>
    const DATA = __DATA__;
    const searchBox = document.getElementById('searchBox');
    const marketSelect = document.getElementById('marketSelect');
    const universeSelect = document.getElementById('universeSelect');
    const timeframeSelect = document.getElementById('timeframeSelect');
    const scoreRange = document.getElementById('scoreRange');
    const scoreText = document.getElementById('scoreText');
    const scanButton = document.getElementById('scanButton');
    const resetButton = document.getElementById('resetButton');
    const rows = document.getElementById('rows');
    const rowCount = document.getElementById('rowCount');
    const generatedAt = document.getElementById('generatedAt');
    const metricCount = document.getElementById('metricCount');
    const metricBest = document.getElementById('metricBest');
    const metricA = document.getElementById('metricA');
    const metricTimeframe = document.getElementById('metricTimeframe');
    const title = document.getElementById('title');
    const subtitle = document.getElementById('subtitle');
    const gradeBadge = document.getElementById('gradeBadge');
    const risk = document.getElementById('risk');
    const fundamental = document.getElementById('fundamental');
    const agents = document.getElementById('agents');
    const chart = document.getElementById('chart');
    const tradingViewLink = document.getElementById('tradingViewLink');
    const chartImageInput = document.getElementById('chartImageInput');
    const imageScanButton = document.getElementById('imageScanButton');
    const imagePreview = document.getElementById('imagePreview');
    const imageMatches = document.getElementById('imageMatches');

    function selectedPatterns() {
      return [...document.querySelectorAll('#patternBox input:checked')].map(item => item.value);
    }

    function weekKey(dateText) {
      const date = new Date(dateText + 'T00:00:00');
      const firstDay = new Date(date.getFullYear(), 0, 1);
      const dayNumber = Math.floor((date - firstDay) / 86400000) + 1;
      const week = Math.ceil((dayNumber + firstDay.getDay()) / 7);
      return `${date.getFullYear()}-W${String(week).padStart(2, '0')}`;
    }

    function aggregateCandles(candles, timeframe) {
      if (timeframe === 'D') return candles;
      const groups = new Map();
      for (const candle of candles) {
        const date = new Date(candle.date + 'T00:00:00');
        const key = timeframe === 'W'
          ? weekKey(candle.date)
          : `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
        if (!groups.has(key)) {
          groups.set(key, {
            date: candle.date,
            open: candle.open,
            high: candle.high,
            low: candle.low,
            close: candle.close,
            volume: candle.volume,
          });
        } else {
          const current = groups.get(key);
          current.date = candle.date;
          current.high = Math.max(current.high, candle.high);
          current.low = Math.min(current.low, candle.low);
          current.close = candle.close;
          current.volume += candle.volume;
        }
      }
      return [...groups.values()];
    }

    function tradingViewSymbol(result) {
      if (result.market === 'TH') return `SET:${result.symbol.replace('.BK', '')}`;
      if (result.symbol.endsWith('.HK')) return `HKEX:${Number(result.symbol.replace('.HK', ''))}`;
      if (result.market === 'CN') {
        if (result.symbol.endsWith('.SS')) return `SSE:${result.symbol.replace('.SS', '')}`;
        if (result.symbol.endsWith('.SZ')) return `SZSE:${result.symbol.replace('.SZ', '')}`;
      }
      return result.symbol;
    }

    function tradingViewSymbolFromIndex(item) {
      if (item.market === 'TH') return `SET:${item.symbol.replace('.BK', '')}`;
      if (item.symbol.endsWith('.HK')) return `HKEX:${Number(item.symbol.replace('.HK', ''))}`;
      if (item.market === 'CN') {
        if (item.symbol.endsWith('.SS')) return `SSE:${item.symbol.replace('.SS', '')}`;
        if (item.symbol.endsWith('.SZ')) return `SZSE:${item.symbol.replace('.SZ', '')}`;
      }
      return item.symbol;
    }

    function resample(values, length = 64) {
      if (!values.length) return [];
      if (values.length === 1) return Array(length).fill(values[0]);
      const output = [];
      for (let i = 0; i < length; i += 1) {
        const position = i * (values.length - 1) / (length - 1);
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
      return values.map(value => (value - mean) / stdev);
    }

    function correlation(a, b) {
      const n = Math.min(a.length, b.length);
      if (!n) return -1;
      let dot = 0;
      for (let i = 0; i < n; i += 1) dot += a[i] * b[i];
      return dot / n;
    }

    function aggregateSeries(series, timeframe) {
      if (timeframe === 'D') return series;
      const groups = new Map();
      for (const point of series) {
        const date = new Date(point.date + 'T00:00:00');
        const key = timeframe === 'W'
          ? weekKey(point.date)
          : `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
        groups.set(key, point);
      }
      return [...groups.values()];
    }

    function interpolateMissing(path) {
      const values = [...path];
      let last = null;
      for (let i = 0; i < values.length; i += 1) {
        if (Number.isFinite(values[i])) {
          if (last === null) {
            for (let j = 0; j < i; j += 1) values[j] = values[i];
          } else if (i - last > 1) {
            const start = values[last];
            const end = values[i];
            for (let j = last + 1; j < i; j += 1) {
              const mix = (j - last) / (i - last);
              values[j] = start * (1 - mix) + end * mix;
            }
          }
          last = i;
        }
      }
      if (last === null) return [];
      for (let i = last + 1; i < values.length; i += 1) values[i] = values[last];
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
            const canvas = document.createElement('canvas');
            canvas.width = width;
            canvas.height = height;
            const ctx = canvas.getContext('2d', { willReadFrequently: true });
            ctx.drawImage(image, 0, 0, width, height);
            const pixels = ctx.getImageData(0, 0, width, height).data;
            const path = [];
            for (let x = 0; x < width; x += 1) {
              let weightedY = 0;
              let weight = 0;
              for (let y = 4; y < height - 4; y += 1) {
                const idx = (y * width + x) * 4;
                const r = pixels[idx];
                const g = pixels[idx + 1];
                const b = pixels[idx + 2];
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
            if (!cleaned.length) reject(new Error('อ่านทรงกราฟจากรูปไม่ได้'));
            else resolve(zscore(resample(cleaned, 64)));
          };
          image.onerror = () => reject(new Error('เปิดรูปไม่ได้'));
          image.src = reader.result;
        };
        reader.onerror = () => reject(new Error('อ่านไฟล์รูปไม่ได้'));
        reader.readAsDataURL(file);
      });
    }

    function scanImageMatches(uploadShape) {
      const market = marketSelect.value;
      const universe = universeSelect.value;
      const timeframe = timeframeSelect.value;
      const matches = [];
      for (const item of DATA.image_index || []) {
        const groups = (item.index_groups || '').split('|');
        if (market !== 'ALL' && item.market !== market) continue;
        if (universe !== 'ALL' && !groups.includes(universe)) continue;
        const points = aggregateSeries(item.series, timeframe).map(point => point.close);
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
        imageMatches.innerHTML = '<p>ไม่พบ asset ที่เทียบได้ ลองเปลี่ยนตลาด/Universe หรือแนบรูปที่เห็นกราฟชัดขึ้น</p>';
        return;
      }
      const scanSymbols = new Set(DATA.results.map(result => result.symbol));
      imageMatches.innerHTML = matches.map(match => {
        const tv = `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tradingViewSymbolFromIndex(match))}`;
        const inScan = scanSymbols.has(match.symbol) ? 'อยู่ในผลสแกน' : 'ยังไม่เข้า pattern filter';
        return `<article class="match-item">
          <span class="match-score">${match.score.toFixed(1)}%</span>
          <div><strong>${match.symbol}</strong><br><span>${match.name} | ${match.market} | ${match.index_groups || '-'}</span><br><span>${inScan}</span></div>
          <a class="link-button" href="${tv}" target="_blank" rel="noreferrer">TV</a>
        </article>`;
      }).join('');
    }

    function decisionClass(text) {
      if (text.includes('Reject')) return 'bad';
      if (text.includes('Candidate') || text.includes('Watchlist')) return 'good';
      return 'warn';
    }

    function filterResults() {
      const query = searchBox.value.trim().toLowerCase();
      const market = marketSelect.value;
      const universe = universeSelect.value;
      const minScore = Number(scoreRange.value);
      const patterns = selectedPatterns();
      return DATA.results.filter(result => {
        const matchesText = !query
          || result.symbol.toLowerCase().includes(query)
          || result.name.toLowerCase().includes(query)
          || result.sector.toLowerCase().includes(query);
        const matchesMarket = market === 'ALL' || result.market === market;
        const groups = (result.index_groups || '').split('|');
        const matchesUniverse = universe === 'ALL' || groups.includes(universe);
        const matchesScore = result.final_score >= minScore;
        const matchesPattern = !patterns.length || result.patterns.some(pattern => patterns.includes(pattern.name));
        return matchesText && matchesMarket && matchesUniverse && matchesScore && matchesPattern;
      });
    }

    function renderMetrics(results) {
      metricCount.textContent = results.length;
      metricBest.textContent = results.length ? results[0].final_score.toFixed(1) : '0';
      metricA.textContent = results.filter(item => item.grade === 'A' || item.grade === 'A+').length;
      metricTimeframe.textContent = timeframeSelect.value;
    }

    function renderRows(results) {
      rowCount.textContent = `${results.length} symbols`;
      if (!results.length) {
        rows.innerHTML = '<tr><td class="empty" colspan="6">ไม่พบหุ้นตามเงื่อนไข ลองลดคะแนนขั้นต่ำหรือเลือก pattern เพิ่ม</td></tr>';
        clearDetail();
        return;
      }
      rows.innerHTML = results.map(result => {
        const pattern = result.patterns[0] ? result.patterns[0].label : '-';
        return `<tr data-symbol="${result.symbol}">
          <td class="symbol"><strong>${result.symbol}</strong><span>${result.name}</span></td>
          <td><span class="chip">${pattern}</span></td>
          <td><span class="badge">${result.grade}</span></td>
          <td>${result.final_score.toFixed(1)}</td>
          <td>${result.fundamental_score.toFixed(1)}</td>
          <td class="${decisionClass(result.decision)}">${result.decision}</td>
        </tr>`;
      }).join('');
      rows.querySelectorAll('tr').forEach(row => row.addEventListener('click', () => selectSymbol(row.dataset.symbol, results)));
      selectSymbol(results[0].symbol, results);
    }

    function clearDetail() {
      title.textContent = 'ไม่พบหุ้น';
      subtitle.textContent = '';
      gradeBadge.textContent = '-';
      risk.innerHTML = '';
      fundamental.innerHTML = '';
      agents.innerHTML = '';
      const ctx = chart.getContext('2d');
      ctx.clearRect(0, 0, chart.width, chart.height);
    }

    function dl(target, pairs) {
      target.innerHTML = '';
      for (const [key, value] of pairs) {
        const dt = document.createElement('dt');
        const dd = document.createElement('dd');
        dt.textContent = key;
        dd.textContent = value;
        target.append(dt, dd);
      }
    }

    function draw(candles, result) {
      const ctx = chart.getContext('2d');
      const width = chart.width;
      const height = chart.height;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = '#fbfcfe';
      ctx.fillRect(0, 0, width, height);
      if (!candles.length) return;
      const pad = { left: 54, right: 18, top: 22, bottom: 42 };
      const maxPrice = Math.max(...candles.map(c => c.high));
      const minPrice = Math.min(...candles.map(c => c.low));
      const span = Math.max(maxPrice - minPrice, .01);
      const x = i => pad.left + i / Math.max(1, candles.length - 1) * (width - pad.left - pad.right);
      const y = p => pad.top + (maxPrice - p) / span * (height - pad.top - pad.bottom);
      ctx.strokeStyle = '#dbe3ee';
      ctx.font = '12px Arial';
      ctx.fillStyle = '#64748b';
      for (let i = 0; i <= 4; i++) {
        const yy = pad.top + (height - pad.top - pad.bottom) * i / 4;
        ctx.beginPath();
        ctx.moveTo(pad.left, yy);
        ctx.lineTo(width - pad.right, yy);
        ctx.stroke();
        ctx.fillText((maxPrice - span * i / 4).toFixed(2), 8, yy + 4);
      }
      const candleW = Math.max(3, (width - pad.left - pad.right) / candles.length * .58);
      candles.forEach((c, i) => {
        const xx = x(i);
        const up = c.close >= c.open;
        ctx.strokeStyle = up ? '#15803d' : '#b91c1c';
        ctx.fillStyle = up ? '#22a35a' : '#dc2626';
        ctx.beginPath();
        ctx.moveTo(xx, y(c.high));
        ctx.lineTo(xx, y(c.low));
        ctx.stroke();
        const top = y(Math.max(c.open, c.close));
        const bottom = y(Math.min(c.open, c.close));
        ctx.fillRect(xx - candleW / 2, top, candleW, Math.max(2, bottom - top));
      });
      const pattern = result.patterns[0];
      if (pattern) {
        ctx.strokeStyle = '#2563eb';
        ctx.setLineDash([5, 4]);
        ctx.beginPath();
        ctx.moveTo(pad.left, y(pattern.level));
        ctx.lineTo(width - pad.right, y(pattern.level));
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#174ea6';
        ctx.fillText(pattern.label + ' ' + pattern.level.toFixed(2), pad.left + 8, y(pattern.level) - 7);
      }
    }

    function selectSymbol(symbol, currentResults) {
      const result = currentResults.find(item => item.symbol === symbol);
      const pack = DATA.symbols[symbol];
      if (!result || !pack) return;
      const chartCandles = aggregateCandles(pack.candles, timeframeSelect.value);
      const latestCandle = chartCandles[chartCandles.length - 1];
      document.querySelectorAll('tbody tr').forEach(row => row.classList.toggle('active', row.dataset.symbol === symbol));
      title.textContent = `${result.symbol} - ${result.name}`;
      subtitle.textContent = `${result.market} | ${(result.index_groups || '-')} | ${result.sector} | TF ${timeframeSelect.value} | Latest ${latestCandle ? latestCandle.date : '-'} | ${result.decision}`;
      gradeBadge.textContent = result.grade;
      tradingViewLink.href = `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tradingViewSymbol(result))}`;
      draw(chartCandles, result);
      dl(risk, [
        ['Bias', result.risk_plan.bias],
        ['Entry', result.risk_plan.entry.toFixed(2)],
        ['Stop', result.risk_plan.stop.toFixed(2)],
        ['Targets', result.risk_plan.targets.map(v => v.toFixed(2)).join(', ')],
        ['R:R', result.risk_plan.reward_risk.toFixed(2) + 'R'],
      ]);
      dl(fundamental, [
        ['ROE/ROA', `${pack.fundamental.roe.toFixed(1)}% / ${pack.fundamental.roa.toFixed(1)}%`],
        ['Debt', pack.fundamental.debt_to_equity.toFixed(2) + 'x'],
        ['Growth', `${pack.fundamental.revenue_growth.toFixed(1)}% / ${pack.fundamental.profit_growth.toFixed(1)}%`],
        ['PE/PBV', result.valuation_verified
          ? `${pack.fundamental.pe.toFixed(1)} / ${pack.fundamental.pbv.toFixed(1)}`
          : 'ยังประเมินมูลค่าไม่ได้'],
        ['สกุลเงินของงบ', result.reporting_currency || 'ยังไม่ตรวจงบ'],
        ['หลักฐานย้อนหลัง', (result.evidence && result.evidence.label) || '-'],
      ]);
      agents.innerHTML = result.insights.map(insight => `<article class="agent"><strong>${insight.agent} (${insight.score.toFixed(1)})</strong><p>${insight.summary}</p></article>`).join('');
    }

    function scan() {
      const results = filterResults();
      renderMetrics(results);
      renderRows(results);
    }

    generatedAt.textContent = `ข้อมูลสร้างเมื่อ ${new Date(DATA.generated_at).toLocaleString()}`;
    document.getElementById('dataSourceNote').textContent = `Data Source: ${DATA.data_source}`;
    // A shared copy keeps whatever prices it was built with, so say so plainly
    // rather than letting a reader assume the numbers moved with the market.
    // The build date is not the data date: an export made on a Saturday still
    // carries Friday's close, so read the date off the candles themselves.
    let snapshotDay = '';
    Object.values(DATA.symbols || {}).forEach((entry) => {
      const candles = entry.candles || [];
      const last = candles.length ? candles[candles.length - 1].date : '';
      if (last > snapshotDay) snapshotDay = last;
    });
    if (!snapshotDay) snapshotDay = (DATA.generated_at || '').slice(0, 10);
    document.getElementById('snapshotNote').textContent = snapshotDay
      ? ` ข้อมูลในหน้านี้เป็นภาพนิ่ง ณ วันที่ ${snapshotDay} และจะไม่อัปเดตตามตลาด`
      : ' ข้อมูลในหน้านี้เป็นภาพนิ่ง และจะไม่อัปเดตตามตลาด';
    scoreRange.addEventListener('input', () => {
      scoreText.textContent = scoreRange.value;
    });
    scanButton.addEventListener('click', scan);
    searchBox.addEventListener('keydown', event => {
      if (event.key === 'Enter') scan();
    });
    resetButton.addEventListener('click', () => {
      searchBox.value = '';
      marketSelect.value = 'ALL';
      universeSelect.value = 'ALL';
      timeframeSelect.value = 'D';
      scoreRange.value = 55;
      scoreText.textContent = '55';
      document.querySelectorAll('#patternBox input').forEach(item => item.checked = true);
      scan();
    });
    chartImageInput.addEventListener('change', () => {
      const file = chartImageInput.files && chartImageInput.files[0];
      if (!file) return;
      imagePreview.src = URL.createObjectURL(file);
      imageMatches.innerHTML = '<p>แนบรูปแล้ว กด Scan รูปกราฟ</p>';
    });
    imageScanButton.addEventListener('click', async () => {
      const file = chartImageInput.files && chartImageInput.files[0];
      if (!file) {
        imageMatches.innerHTML = '<p>กรุณาแนบรูปกราฟก่อน</p>';
        return;
      }
      imageMatches.innerHTML = '<p>กำลังอ่านรูปและเทียบทรงกราฟ...</p>';
      try {
        const shape = await extractImageShape(file);
        renderImageMatches(scanImageMatches(shape));
      } catch (error) {
        imageMatches.innerHTML = `<p>${error.message}</p>`;
      }
    });
    scan();
  </script>
</body>
</html>"""
    return html.replace("__DATA__", data_json)


def export_static_dashboard(path: str | Path, criteria: ScanCriteria | None = None) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_static_dashboard_html(criteria), encoding="utf-8")
    return output
