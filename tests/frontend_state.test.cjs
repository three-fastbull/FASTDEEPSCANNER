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
    document: { getElementById: element, querySelectorAll: () => [] },
    window, URLSearchParams, Intl, Date,
    CustomEvent: class { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } },
    fetch: async () => ({ ok: false, json: async () => ({ error: 'test startup' }) }),
  });
  let source = fs.readFileSync(path.join(__dirname, '..', 'fastdeep_web', script), 'utf8');
  if (script === 'financial.js') {
    assert.ok(source.startsWith('(() => {'));
    assert.ok(source.trimEnd().endsWith('})();'));
    source = source.slice(source.indexOf('\n') + 1, source.lastIndexOf('})();'));
    source = source.replace('if (!elements.symbolInput) return;', '');
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
