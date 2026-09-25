// Regression: an incomplete air diagnostic must never look like a passed check.
// Run with: node web/air_render_test.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('./verdict.js', import.meta.url), 'utf8');
const airFunctions = source.slice(source.indexOf('function airSignalRows'), source.indexOf('function renderAirResearch'));
const context = vm.createContext({
  escapeHtml: (value) => String(value ?? '').replaceAll('<', '&lt;'),
  fmtSigned: (_signal, value) => Number.isFinite(value) ? `${value} µg/m³` : '—',
});
vm.runInContext(airFunctions, context);
const fixture = {
  signals: { NO2_TRAFFIC: {
    point: -4, relative_pct: -10, placebo_p: .04, placebo_p_effect: .03,
    treated_station_count: 4, treated_station_requested: 5, n_donors: 20,
    placebo_n: 25, site_type: 'traffic',
  } }, charts: { NO2_TRAFFIC: {} },
};
context.fixture = fixture;
let html = vm.runInContext('renderAirCharts(fixture)', context);
assert.match(html, /Pre-trend: not run/);
assert.match(html, /interval search: not available/);
assert.doesNotMatch(html, /Pre-trend: clear/);
assert.match(html, /90% confidence interval/);
assert.match(html, /London \/ control monitors/);
fixture.signals.NO2_TRAFFIC = {
  ...fixture.signals.NO2_TRAFFIC, lo: -7, hi: -1,
  pretrend: { flagged: true }, conformal_boundary_hit: true,
};
html = vm.runInContext('renderAirCharts(fixture)', context);
assert.match(html, /Pre-trend: flagged/);
assert.match(html, /interval search: unresolved/);
assert.match(html, /-7 µg\/m³ to -1 µg\/m³/);
fixture.signals.NO2_TRAFFIC.pretrend.flagged = false;
fixture.signals.NO2_TRAFFIC.conformal_boundary_hit = false;
html = vm.runInContext('renderAirCharts(fixture)', context);
assert.match(html, /Pre-trend: clear/);
assert.match(html, /interval search: resolved/);
fixture.signals.NO2_TRAFFIC = {
  ...fixture.signals.NO2_TRAFFIC, point: null, lo: null, hi: null,
  relative_pct: null, placebo_p: null, placebo_p_effect: null,
};
html = vm.runInContext('renderAirCharts(fixture)', context);
assert.doesNotMatch(html, /0\.000|0\.0%|null/);
assert.match(html, /interval search: not available/);

fixture.signals.NO2_TRAFFIC.pretrend = { applicable: false, flagged: false };
html = vm.runInContext('renderAirCharts(fixture)', context);
assert.match(html, /Pre-trend: not run/);

// Zero placebo cohorts: no p-value and no "0 cohorts reran..." claim, even when
// an older run file carries the p = 1.0 sentinel.
fixture.signals.NO2_TRAFFIC = { ...fixture.signals.NO2_TRAFFIC, placebo_n: 0, placebo_p: 1, placebo_p_effect: 1 };
html = vm.runInContext('renderAirCharts(fixture)', context);
assert.doesNotMatch(html, /1\.000/);
assert.match(html, /no placebo test and no placebo p-value/);
assert.doesNotMatch(html, /0 exact-size placebo cohorts reran/);

const charts = readFileSync(new URL('./chart.js', import.meta.url), 'utf8');
vm.runInContext(charts.slice(charts.indexOf('function linePath'), charts.indexOf('/** Shared frame')), context);
assert.equal(vm.runInContext('bandPathD([0,1], [null,null], [null,null], x=>x, y=>y)', context), '');
assert.equal(vm.runInContext('linePath([0,1,2], [4,null,6], x=>x, y=>y)', context), 'M0,4M2,6');
assert.equal(vm.runInContext('JSON.stringify(addBandToCounterfactual([null,1], [30,40]))', context), '[null,41]');
assert.equal(vm.runInContext('JSON.stringify(addBandToCounterfactual([1,1], [null,40]))', context), '[null,41]');
const partialBand = vm.runInContext('bandPathD([0,1,2], [1,null,2], [3,null,4], x=>x, y=>y)', context);
assert.equal(partialBand, 'M0,3 L0,1 ZM2,4 L2,2 Z');
console.log('Air rendering regression checks passed.');
