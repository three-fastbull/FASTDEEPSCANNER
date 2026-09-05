const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

async function appHarness(script = 'app.js') {
  const elements = new Map();
  const listeners = new Map();
  function element(id) {
    if (!elements.has(id)) {
      const classes = new Set();
      elements.set(id, {
        value: id === 'timeframeSelect' ? 'D' : id === 'scoreRange' ? '70' : 'ALL',
        textContent: '', href: '', dataset: {},
        closest: (selector) => element(selector),
        addEventListener() {},
        classList: {
          contains: (name) => classes.has(name),
          add: (name) => classes.add(name),
          remove: (name) => classes.delete(name),
          toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name),
        },
      });
    }
    return elements.get(id);
  }
  const window = {
    addEventListener(name, callback) {
      listeners.set(name, [...(listeners.get(name) || []), callback]);
    },
    dispatchEvent(event) {
      for (const callback of listeners.get(event.type) || []) callback(event);
    },
  };
  const context = vm.createContext({
    document: { getElementById: element, querySelectorAll: () => [], querySelector: () => null },
    window, URLSearchParams, URL, Intl, Date,
    CustomEvent: class { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } },
    fetch: async () => ({ ok: false, json: async () => ({ error: 'test startup' }) }),
  });
  let source = fs.readFileSync(path.join(__dirname, '..', 'fastdeep_web', script), 'utf8');
  if (script === 'financial.js' || script === 'profile.js') {
    const start = source.indexOf('(() => {');
    assert.ok(start >= 0);
    assert.ok(source.trimEnd().endsWith('})();'));
    source = source.slice(start + '(() => {'.length, source.lastIndexOf('})();'));
    source = source.replace('if (!elements.symbolInput) return;', '');
    source = source.replace('if (!elements.view) return;', '');
  }
  await vm.runInContext(source, context);
  return { context, window, element };
}

function queuedFetch(context) {
  const pending = [];
  context.fetch = (url) => new Promise((resolve) => pending.push({
    url, resolve: (payload) => resolve({ ok: true, json: async () => payload }),
  }));
  return pending;
}

test('a late stock response cannot replace the most recent stock selection', async () => {
  const { context, window } = await appHarness();
  const rendered = [];
  context.renderDetail = (payload) => rendered.push(payload.result.symbol);
  const pending = queuedFetch(context);
  const first = context.loadSymbol('AAPL');
  const second = context.loadSymbol('FIX');
  pending[1].resolve({ result: { symbol: 'FIX' } });
  await second;
  pending[0].resolve({ result: { symbol: 'AAPL' } });
  await first;
  assert.deepEqual(rendered, ['FIX']);
  assert.equal(window.fastDeepSelectedSymbol, 'FIX');
});

test('a stock selected in another view cancels the pending scanner detail', async () => {
  const { context, window } = await appHarness();
  const rendered = [];
  context.renderDetail = (payload) => rendered.push(payload.result.symbol);
  const pending = queuedFetch(context);
  const request = context.loadSymbol('AAPL');
  window.fastDeepSelectedSymbol = 'FIX';
  window.dispatchEvent({ type: 'fastdeep:symbol-selected', detail: { symbol: 'FIX', source: 'hall-of-fame' } });
  pending[0].resolve({ result: { symbol: 'AAPL' } });
  await request;
  assert.deepEqual(rendered, []);
  assert.equal(window.fastDeepSelectedSymbol, 'FIX');
});

test('only the latest scan response updates the result table', async () => {
  const { context } = await appHarness();
  const displayed = [];
  context.renderDataHealth = () => {};
  context.renderMetrics = () => {};
  context.renderTable = (rows) => displayed.push(rows[0].symbol);
  context.loadSymbol = async () => {};
  const pending = queuedFetch(context);
  const first = context.runScan();
  const second = context.runScan();
  pending[1].resolve({ results: [{ symbol: 'FIX' }] });
  await second;
  pending[0].resolve({ results: [{ symbol: 'AAPL' }] });
  await first;
  assert.deepEqual(displayed, ['FIX']);
});

test('changing filters clears old metrics and hides the old stock while scanning', async () => {
  const { context, element, window } = await appHarness();
  window.fastDeepSelectedSymbol = 'AAPL';
  element('detailTitle').textContent = 'AAPL';
  element('.detail-panel').dataset.state = 'ready';
  element('metricCount').textContent = '64';
  const pending = queuedFetch(context);
  context.renderDataHealth = () => {};
  context.renderMetrics = () => {};
  context.renderTable = () => {};
  const request = context.runScan();
  assert.equal(element('metricCount').textContent, '...');
  assert.equal(element('.detail-panel').dataset.state, 'empty');
  assert.notEqual(element('detailTitle').textContent, 'AAPL');
  pending[0].resolve({ results: [] });
  await request;
  assert.equal(element('.detail-panel').dataset.state, 'empty');
  assert.equal(window.fastDeepSelectedSymbol, 'AAPL');
});

test('resizing only redraws the chart and preserves the shared selected stock', async () => {
  const { context, window } = await appHarness();
  let requests = 0;
  let redraws = 0;
  context.fetch = async () => { requests += 1; throw new Error('Unexpected fetch'); };
  context.drawChart = () => { redraws += 1; };
  context.aggregateCandles = (candles) => candles;
  vm.runInContext('state.detailPayload = {candles: [], result: {symbol: "AAPL"}};', context);
  window.fastDeepSelectedSymbol = 'FIX';
  window.dispatchEvent({ type: 'resize' });
  assert.equal(requests, 0);
  assert.equal(redraws, 1);
  assert.equal(window.fastDeepSelectedSymbol, 'FIX');
});

test('thesis progress is bounded and handles debt-free and invalid targets', async () => {
  const { context } = await appHarness('financial.js');
  assert.equal(context.targetProgress(30, 10), 100);
  assert.equal(context.targetProgress(5, 10), 50);
  assert.equal(context.targetProgress(0, 1.5, { inverse: true }), 100);
  assert.equal(context.targetProgress(-1, 1.5, { inverse: true }), 0);
  assert.equal(context.targetProgress(5, 0), null);
  assert.equal(context.targetProgress(null, 10), null);
});

test('financial quarters include the current interim year before an annual filing exists', async () => {
  const { context, element } = await appHarness('financial.js');
  vm.runInContext(`state.financials = {
    symbol: 'TEST', annual: [{fiscal_year: '2025', period_end: '2025-12-31'}],
    quarterly_by_year: {'2025': [], '2026': [{quarter: 'Q1', period_end: '2026-03-31', metrics: {}}]},
    sections: []
  }; state.selectedYear = '2026'; renderQuarterly();`, context);
  assert.match(element('quarterlyYearSelect').innerHTML, /value="2026" selected/);
  assert.match(element('quarterlyYearSelect').innerHTML, /ระหว่างปี/);
  assert.match(element('quarterlyTitle').textContent, /2026/);
  assert.match(element('quarterlyPeriodNote').textContent, /1\/4/);
});

test('financial provenance distinguishes reported EPS from derived cash flows', async () => {
  const { context } = await appHarness('financial.js');
  const period = {metrics: {basic_eps: 1.25, operating_cash_flow: 200}, metric_sources: {
    basic_eps: {kind: 'reported', source_form: '10-K', filed_at: '2026-03-01'},
    operating_cash_flow: {kind: 'derived_ytd_difference'},
  }};
  assert.match(context.metricProvenance(period, 'basic_eps'), /10-K/);
  assert.match(context.metricProvenance(period, 'operating_cash_flow'), /ยอดสะสม/);
  assert.match(context.metricProvenance(period, 'total_revenue'), /ยังไม่มีข้อมูล/);
});

test('mobile charts use their actual CSS width and zero volume never draws NaN', async () => {
  const { context, window, element } = await appHarness();
  const canvas = element('priceChart');
  const rectangles = [];
  const drawContext = {};
  for (const method of ['scale', 'clearRect', 'beginPath', 'moveTo', 'lineTo', 'stroke', 'fillText', 'setLineDash']) {
    drawContext[method] = () => {};
  }
  drawContext.fillRect = (...args) => rectangles.push(args);
  canvas.getContext = () => drawContext;
  canvas.getBoundingClientRect = () => ({ width: 300, height: 320 });
  const candles = [{ open: 10, high: 11, low: 9, close: 10.5, volume: 0 }];
  const result = { patterns: [], symbol: 'TEST', last_price: 10.5, market_phase: 'RUN' };
  window.devicePixelRatio = 1;
  context.drawChart(candles, result);
  assert.equal(canvas.width, 300);
  window.devicePixelRatio = 2;
  context.drawChart(candles, result);
  assert.equal(canvas.width, 600);
  assert.ok(rectangles.flat().every(Number.isFinite));
});

test('small year changes do not become negative zero', async () => {
  const { context } = await appHarness('financial.js');
  const badge = context.changeBadge(352583, 352755, 'total_assets');
  assert.match(badge, /&lt;0\.1%/);
  assert.doesNotMatch(badge, /-0%/);
});

test('profit recoveries and ratio changes have distinct labels', async () => {
  const { context } = await appHarness('financial.js');
  assert.match(context.changeBadge(100, -20, 'net_income'), /data-tone="ok"/);
  assert.doesNotMatch(context.changeBadge(100, -20, 'net_income'), /%/);
  assert.match(context.changeBadge(12.5, 10, 'net_margin', true), /\+2\.5/);
  assert.match(context.changeBadge(0.4, 0.5, 'debt_to_equity', true), /-0\.1x/);
});

function referenceProfile(symbol = 'TRV') {
  const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'data', 'fastdeep_company_profiles.json'), 'utf8'));
  const reference = { ...catalog.profiles[symbol], available: true, catalog_count: Object.keys(catalog.profiles).length };
  const breakdown = reference.revenue_breakdown;
  breakdown.segments.forEach((segment) => {
    segment.share_pct = breakdown.total ? segment.amount / breakdown.total * 100 : null;
  });
  return {
    symbol, name: reference.name, available: false, research: {}, qualitative: {},
    business: {
      summary: reference.summary, revenue_model: reference.revenue_model,
      key_customers: reference.key_customers, moat_evidence: reference.moat_summary,
      reference, field_origins: {}, verified: false,
    },
  };
}

test('company sections show sourced facts, revenue shares, peers and separate moat judgement', async () => {
  const { context, element } = await appHarness('profile.js');
  context.renderBusiness(referenceProfile());
  context.renderCompetition(referenceProfile());
  const business = element('profileBusiness').innerHTML;
  const competition = element('profileCompetition').innerHTML;
  assert.match(business, /51\.1%/);
  assert.match(business, /เบี้ยประกันภัยรับสุทธิ/);
  assert.match(business, /Travelers: ผลประกอบการปี 2025/);
  assert.doesNotMatch(business, /ยังไม่มีคำอธิบายธุรกิจ/);
  assert.match(competition, /Chubb/);
  assert.match(competition, /The Hartford/);
  assert.match(competition, /Progressive/);
  assert.match(competition, /ข้อวิเคราะห์/);
  assert.match(competition, /Moat ที่คุณประเมิน: <strong>ยังไม่ประเมิน/);
});

test('source material is not silently copied into the private research form', async () => {
  const { context, element } = await appHarness('profile.js');
  const profile = referenceProfile();
  context.renderResearchEditor(profile);
  assert.equal(element('profileBusinessSummary').value, '');
  assert.equal(element('profileMoatEvidence').value, '');
  assert.equal(element('profileSourceUrls').value, '');
  assert.equal(element('profileResearchMoat').value, '');
  assert.equal(element('profileResearchDecision').value, 'Watch');
  profile.research = { business_summary: 'My saved company note', competitors: 'My peer' };
  context.renderResearchEditor(profile);
  assert.equal(element('profileBusinessSummary').value, 'My saved company note');
  assert.equal(element('profileCompetitors').value, 'My peer');
});

test('manual revenue and competitor notes replace the matching reference presentation', async () => {
  const { context, element } = await appHarness('profile.js');
  const profile = referenceProfile();
  profile.business.revenue_segments = 'My revenue analysis';
  profile.business.competitors = 'My comparison company';
  profile.business.field_origins = { revenue_segments: 'journal', competitors: 'journal' };
  context.renderBusiness(profile);
  context.renderCompetition(profile);
  assert.match(element('profileBusiness').innerHTML, /My revenue analysis/);
  assert.doesNotMatch(element('profileBusiness').innerHTML, /51\.1%/);
  assert.match(element('profileCompetition').innerHTML, /My comparison company/);
  assert.doesNotMatch(element('profileCompetition').innerHTML, /<strong>Chubb/);
});

test('unknown revenue mix is shown without an invented zero or percentage bar', async () => {
  const { context, element } = await appHarness('profile.js');
  context.renderBusiness(referenceProfile('DOHOME.BK'));
  const html = element('profileBusiness').innerHTML;
  assert.match(html, /วัสดุก่อสร้าง/);
  assert.doesNotMatch(html, /segment-track|0%/);
});

test('company descriptions, peers and source URLs cannot inject markup or executable links', async () => {
  const { context, element } = await appHarness('profile.js');
  const profile = referenceProfile();
  profile.business.summary = '<script>alert(1)</script>';
  profile.business.reference.peers[0].name = '<img src=x onerror=alert(1)>';
  profile.business.reference.sources[0].url = 'javascript:alert(1)';
  context.renderBusiness(profile);
  context.renderCompetition(profile);
  const html = element('profileBusiness').innerHTML + element('profileCompetition').innerHTML;
  assert.doesNotMatch(html, /<script>|<img src=x|href="javascript:/);
  assert.match(html, /&lt;script&gt;/);
});

test('a late company response does not replace the selected company in sections one and two', async () => {
  const { context, element } = await appHarness('profile.js');
  context.renderQualitative = () => {};
  context.renderFlow = () => {};
  const pending = queuedFetch(context);
  const first = context.loadProfile('AAPL');
  const second = context.loadProfile('TRV');
  pending[1].resolve(referenceProfile('TRV'));
  await second;
  pending[0].resolve(referenceProfile('AAPL'));
  await first;
  assert.match(element('profileBusiness').innerHTML, /เบี้ยประกัน/);
  assert.match(element('profileCompetition').innerHTML, /Chubb/);
  assert.doesNotMatch(element('profileBusiness').innerHTML, /iPhone/);
});
