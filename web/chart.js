// Otherwise — dependency-free inline SVG charts for the verdict page.
//
// drawTrajectoryChart(container, chart, opts) -> { reveal() }
//   Counterfactual and placebo band are drawn at once; the actual line is
//   held back (stroke-dashoffset) until reveal() is called, then draws in
//   over ~1.1 s. Pass { animate: false } to draw everything immediately
//   (resize redraws, reduced motion).
// drawGapChart(container, chart, opts)
import { fmtSignalValue, fmtDate } from "./common.js";

const SVGNS = "http://www.w3.org/2000/svg";
const MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const REDUCED = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Axis/annotation number: proper minus sign, and no sign on a value that rounds to zero. */
function fmtNum(signal, value, opts) {
  const s = fmtSignalValue(signal, value, opts);
  if (/^[-+]0(\.0+)?( dB)?$/.test(s)) return s.slice(1);
  return s.replace(/^-/, "\u2212");
}

function parseISO(iso) {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

function svgEl(tag, attrs) {
  const e = document.createElementNS(SVGNS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}

function scale(domain, range) {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  return (v) => r0 + ((v - d0) / span) * (r1 - r0);
}

function niceStep(rough) {
  const mag = Math.pow(10, Math.floor(Math.log10(Math.max(rough, 1e-9))));
  const norm = rough / mag;
  let step;
  if (norm <= 1) step = 1;
  else if (norm <= 2) step = 2;
  else if (norm <= 5) step = 5;
  else step = 10;
  return step * mag;
}

function yTicks(min, max, count) {
  if (min === max) { min -= 1; max += 1; }
  const step = niceStep((max - min) / count);
  const start = Math.ceil(min / step) * step;
  const ticks = [];
  for (let v = start; v <= max + 1e-9; v += step) ticks.push(Math.round(v / step) * step);
  return ticks;
}

/** A handful of evenly-spaced month/year tick marks across a time domain. */
function xTicks(tMin, tMax, targetCount) {
  const spanDays = (tMax - tMin) / 86400000;
  const monthsSpan = spanDays / 30.4;
  let stepMonths = 1;
  const candidates = [1, 2, 3, 6, 12, 24];
  for (const c of candidates) {
    if (monthsSpan / c <= targetCount) { stepMonths = c; break; }
    stepMonths = c;
  }
  // a narrow chart still gets at least three labelled ticks
  while (stepMonths > 1 && monthsSpan / stepMonths < 3) {
    stepMonths = candidates[Math.max(0, candidates.indexOf(stepMonths) - 1)];
  }
  const start = new Date(tMin);
  let y = start.getUTCFullYear();
  let m = start.getUTCMonth();
  m = Math.ceil(m / stepMonths) * stepMonths;
  y += Math.floor(m / 12);
  m = m % 12;
  const ticks = [];
  let t = Date.UTC(y, m, 1);
  while (t <= tMax) {
    ticks.push(t);
    m += stepMonths;
    y += Math.floor(m / 12);
    m = m % 12;
    t = Date.UTC(y, m, 1);
  }
  return ticks;
}

function xTickLabel(t) {
  const d = new Date(t);
  return `${MONTHS_SHORT[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

function tooltipDate(t) {
  const d = new Date(t);
  return `${d.getUTCDate()} ${MONTHS_SHORT[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

function getOrMakeTooltip(wrap) {
  let tip = wrap.querySelector(".chart-tooltip");
  if (!tip) {
    tip = document.createElement("div");
    tip.className = "chart-tooltip";
    tip.style.display = "none";
    wrap.appendChild(tip);
  }
  return tip;
}

function nearestIndex(times, t) {
  let lo = 0, hi = times.length - 1;
  if (t <= times[0]) return 0;
  if (t >= times[hi]) return hi;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (times[mid] < t) lo = mid; else hi = mid;
  }
  return t - times[lo] <= times[hi] - t ? lo : hi;
}

function linePath(times, values, x, y) {
  let d = "";
  for (let i = 0; i < times.length; i++) {
    if (!Number.isFinite(values[i])) continue;
    d += (d ? " L" : "M") + `${x(times[i])},${y(values[i])}`;
  }
  return d;
}

function bandPathD(times, lo, hi, x, y) {
  let d = `M${x(times[0])},${y(hi[0])}`;
  for (let i = 1; i < times.length; i++) d += ` L${x(times[i])},${y(hi[i])}`;
  for (let i = times.length - 1; i >= 0; i--) d += ` L${x(times[i])},${y(lo[i])}`;
  return d + " Z";
}

/** Shared frame: post-event tint, hairline y grid, x/y axis type at 12px. */
function drawFrame(svg, { width, height, margin, x, y, yMin, yMax, tMin, tMax, eventT, signal, signed, yCount }) {
  if (eventT < tMax) {
    svg.appendChild(svgEl("rect", {
      x: x(Math.max(eventT, tMin)), y: margin.top, width: Math.max(x(tMax) - x(Math.max(eventT, tMin)), 0),
      height: height - margin.top - margin.bottom, fill: "rgba(22,22,22,0.035)",
    }));
  }
  for (const t of yTicks(yMin, yMax, yCount)) {
    const ty = y(t);
    svg.appendChild(svgEl("line", { x1: margin.left, x2: width - margin.right, y1: ty, y2: ty, stroke: "var(--rule)", "stroke-width": 1, "shape-rendering": "crispEdges" }));
    const lbl = svgEl("text", { x: margin.left - 10, y: ty + 4, "text-anchor": "end", class: "axis num" });
    lbl.textContent = fmtNum(signal, t, { sign: signed });
    svg.appendChild(lbl);
  }
  for (const t of xTicks(tMin, tMax, Math.max(4, Math.floor(width / 120)))) {
    const lbl = svgEl("text", { x: x(t), y: height - margin.bottom + 20, "text-anchor": "middle", class: "axis" });
    lbl.textContent = xTickLabel(t);
    svg.appendChild(lbl);
  }
}

function eventLine(svg, { ex, margin, height, label }) {
  svg.appendChild(svgEl("line", { x1: ex, x2: ex, y1: margin.top, y2: height - margin.bottom, stroke: "var(--ink)", "stroke-width": 1, opacity: 0.55, "shape-rendering": "crispEdges" }));
  if (label) {
    const lbl = svgEl("text", { x: ex - 6, y: margin.top + 4, "text-anchor": "end", class: "axis" });
    lbl.textContent = label;
    svg.appendChild(lbl);
  }
}

function attachHover(svg, hitRect, { times, x, width, tMin, tMax, margin }, onIndex, onLeave) {
  hitRect.addEventListener("mousemove", (e) => {
    const rect = svg.getBoundingClientRect();
    const scaleX = width / rect.width;
    const px = (e.clientX - rect.left) * scaleX;
    const t = (px - margin.left) / (width - margin.left - margin.right) * (tMax - tMin) + tMin;
    onIndex(nearestIndex(times, t));
  });
  hitRect.addEventListener("mouseleave", onLeave);
}

/**
 * Trajectory chart: area (actual) vs counterfactual, placebo band, event line.
 * Returns { reveal } — call reveal() when the chart scrolls into view.
 */
export function drawTrajectoryChart(container, chart, { eventDate, signal, animate = true }) {
  const width = Math.max(container.clientWidth || 640, 280);
  const height = width < 640 ? 260 : 360;
  const margin = { top: 24, right: 16, bottom: 34, left: 60 };
  container.innerHTML = "";
  const wrap = container;

  const times = chart.dates.map(parseISO);
  const eventT = parseISO(eventDate);
  const tMin = Math.min(times[0], eventT);
  const tMax = Math.max(times[times.length - 1], eventT);

  const bandLo = chart.placebo_band[0].map((v, i) => chart.counterfactual[i] + v);
  const bandHi = chart.placebo_band[1].map((v, i) => chart.counterfactual[i] + v);
  const allY = [...chart.treated, ...chart.counterfactual, ...bandLo, ...bandHi].filter((v) => Number.isFinite(v));
  let yMin = Math.min(...allY), yMax = Math.max(...allY);
  const pad = (yMax - yMin) * 0.08 || 0.05;
  yMin -= pad; yMax += pad;

  const x = scale([tMin, tMax], [margin.left, width - margin.right]);
  const y = scale([yMin, yMax], [height - margin.bottom, margin.top]);

  const svg = svgEl("svg", { width, height, viewBox: `0 0 ${width} ${height}`, style: "display:block;width:100%;height:auto;", role: "img", "aria-label": "Actual trajectory of the area against its no-event counterfactual" });
  drawFrame(svg, { width, height, margin, x, y, yMin, yMax, tMin, tMax, eventT, signal, signed: false, yCount: 4 });

  // 1. placebo band and counterfactual: present from the start
  svg.appendChild(svgEl("path", { d: bandPathD(times, bandLo, bandHi, x, y), fill: "var(--band)", stroke: "none" }));
  svg.appendChild(svgEl("path", { d: linePath(times, chart.counterfactual, x, y), fill: "none", stroke: "var(--counter)", "stroke-width": 1.5, "stroke-dasharray": "5,4", "stroke-linejoin": "round" }));

  // 2. event line with label
  if (eventT >= tMin && eventT <= tMax) {
    eventLine(svg, { ex: x(eventT), margin, height, label: `event · ${fmtDate(eventDate)}` });
  }

  // 3. actual line + observation dots (draw in on reveal)
  const actual = svgEl("path", { d: linePath(times, chart.treated, x, y), fill: "none", stroke: "var(--treated)", "stroke-width": 1.6, "stroke-linejoin": "round", "stroke-linecap": "round", class: "line-actual" });
  svg.appendChild(actual);
  const dots = svgEl("g", { class: "dots-actual" });
  for (let i = 0; i < times.length; i++) {
    if (chart.n_obs && chart.n_obs[i] > 0 && Number.isFinite(chart.treated[i])) {
      dots.appendChild(svgEl("circle", { cx: x(times[i]), cy: y(chart.treated[i]), r: 2.2, fill: "var(--treated)" }));
    }
  }
  svg.appendChild(dots);

  // hover crosshair (hidden by default)
  const hoverLine = svgEl("line", { x1: 0, x2: 0, y1: margin.top, y2: height - margin.bottom, stroke: "var(--ink)", "stroke-width": 1, opacity: 0, "shape-rendering": "crispEdges" });
  const hoverDotT = svgEl("circle", { r: 3.4, fill: "var(--treated)", opacity: 0 });
  const hoverDotC = svgEl("circle", { r: 3.4, fill: "var(--counter)", opacity: 0 });
  svg.appendChild(hoverLine); svg.appendChild(hoverDotT); svg.appendChild(hoverDotC);
  const hitRect = svgEl("rect", { x: margin.left, y: margin.top, width: width - margin.left - margin.right, height: height - margin.top - margin.bottom, fill: "transparent" });
  svg.appendChild(hitRect);

  wrap.appendChild(svg);
  const tip = getOrMakeTooltip(wrap);

  attachHover(svg, hitRect, { times, x, width, tMin, tMax, margin }, (i) => {
    const cx = x(times[i]);
    hoverLine.setAttribute("x1", cx); hoverLine.setAttribute("x2", cx); hoverLine.setAttribute("opacity", 0.6);
    hoverDotT.setAttribute("cx", cx); hoverDotT.setAttribute("cy", y(chart.treated[i])); hoverDotT.setAttribute("opacity", 1);
    hoverDotC.setAttribute("cx", cx); hoverDotC.setAttribute("cy", y(chart.counterfactual[i])); hoverDotC.setAttribute("opacity", 1);
    const gap = chart.treated[i] - chart.counterfactual[i];
    tip.innerHTML = `${tooltipDate(times[i])}<br>Actual ${fmtNum(signal, chart.treated[i])}<br>Counterfactual ${fmtNum(signal, chart.counterfactual[i])}<br>Gap ${fmtNum(signal, gap, { sign: true })}`;
    tip.style.display = "block";
    tip.style.left = `${(cx / width) * 100}%`;
    tip.style.top = `${(Math.min(y(chart.treated[i]), y(chart.counterfactual[i])) / height) * 100}%`;
  }, () => {
    tip.style.display = "none";
    hoverLine.setAttribute("opacity", 0);
    hoverDotT.setAttribute("opacity", 0);
    hoverDotC.setAttribute("opacity", 0);
  });

  // draw-in: hold the actual line back until reveal()
  const doAnimate = animate && !REDUCED;
  let revealed = !doAnimate;
  if (doAnimate) {
    const len = actual.getTotalLength ? actual.getTotalLength() : 0;
    if (len > 0) {
      actual.style.strokeDasharray = `${len}`;
      actual.style.strokeDashoffset = `${len}`;
      actual.style.transition = "stroke-dashoffset 1.1s ease-out";
    }
    dots.style.opacity = "0";
    dots.style.transition = "opacity 0.3s ease-out 0.9s";
  }
  return {
    reveal() {
      if (revealed) return;
      revealed = true;
      requestAnimationFrame(() => {
        actual.style.strokeDashoffset = "0";
        dots.style.opacity = "1";
      });
    },
  };
}

/** The gap (effect) chart: effect vs. zero, with its placebo band. */
export function drawGapChart(container, chart, { eventDate, signal }) {
  const width = Math.max(container.clientWidth || 640, 280);
  const height = width < 640 ? 200 : 240;
  const margin = { top: 20, right: 16, bottom: 34, left: 60 };
  container.innerHTML = "";
  const wrap = container;

  const times = chart.dates.map(parseISO);
  const eventT = parseISO(eventDate);
  const tMin = Math.min(times[0], eventT);
  const tMax = Math.max(times[times.length - 1], eventT);

  const bandLo = chart.placebo_band[0];
  const bandHi = chart.placebo_band[1];
  const allY = [...chart.effect, ...bandLo, ...bandHi, 0].filter((v) => Number.isFinite(v));
  let yMin = Math.min(...allY), yMax = Math.max(...allY);
  const pad = (yMax - yMin) * 0.12 || 0.05;
  yMin -= pad; yMax += pad;

  const x = scale([tMin, tMax], [margin.left, width - margin.right]);
  const y = scale([yMin, yMax], [height - margin.bottom, margin.top]);

  const svg = svgEl("svg", { width, height, viewBox: `0 0 ${width} ${height}`, style: "display:block;width:100%;height:auto;", role: "img", "aria-label": "Gap between the area and its counterfactual over time" });
  drawFrame(svg, { width, height, margin, x, y, yMin, yMax, tMin, tMax, eventT, signal, signed: true, yCount: 3 });

  svg.appendChild(svgEl("path", { d: bandPathD(times, bandLo, bandHi, x, y), fill: "var(--band)", stroke: "none" }));
  // zero line
  svg.appendChild(svgEl("line", { x1: margin.left, x2: width - margin.right, y1: y(0), y2: y(0), stroke: "var(--ink)", "stroke-width": 1, opacity: 0.45, "shape-rendering": "crispEdges" }));
  svg.appendChild(svgEl("path", { d: linePath(times, chart.effect, x, y), fill: "none", stroke: "var(--treated)", "stroke-width": 1.6, "stroke-linejoin": "round" }));
  if (eventT >= tMin && eventT <= tMax) eventLine(svg, { ex: x(eventT), margin, height, label: "event" });

  const hoverLine = svgEl("line", { x1: 0, x2: 0, y1: margin.top, y2: height - margin.bottom, stroke: "var(--ink)", "stroke-width": 1, opacity: 0, "shape-rendering": "crispEdges" });
  const hoverDot = svgEl("circle", { r: 3.4, fill: "var(--treated)", opacity: 0 });
  svg.appendChild(hoverLine); svg.appendChild(hoverDot);
  const hitRect = svgEl("rect", { x: margin.left, y: margin.top, width: width - margin.left - margin.right, height: height - margin.top - margin.bottom, fill: "transparent" });
  svg.appendChild(hitRect);

  wrap.appendChild(svg);
  const tip = getOrMakeTooltip(wrap);

  attachHover(svg, hitRect, { times, x, width, tMin, tMax, margin }, (i) => {
    const cx = x(times[i]);
    hoverLine.setAttribute("x1", cx); hoverLine.setAttribute("x2", cx); hoverLine.setAttribute("opacity", 0.6);
    hoverDot.setAttribute("cx", cx); hoverDot.setAttribute("cy", y(chart.effect[i])); hoverDot.setAttribute("opacity", 1);
    tip.innerHTML = `${tooltipDate(times[i])}<br>Gap ${fmtNum(signal, chart.effect[i], { sign: true })}`;
    tip.style.display = "block";
    tip.style.left = `${(cx / width) * 100}%`;
    tip.style.top = `${(y(chart.effect[i]) / height) * 100}%`;
  }, () => {
    tip.style.display = "none";
    hoverLine.setAttribute("opacity", 0);
    hoverDot.setAttribute("opacity", 0);
  });
}

/**
 * Placebo strip: every control cell's effect as a tick, zero marked, the
 * area as a coloured dot. Returns an SVG string.
 */
export function stripPlotSVG(width, effects, point, colorVar, signal) {
  const height = 64;
  const mx = 12;
  const all = [...effects, point, 0].filter((v) => Number.isFinite(v));
  let dMin = Math.min(...all), dMax = Math.max(...all);
  const pad = (dMax - dMin) * 0.12 || 0.1;
  dMin -= pad; dMax += pad;
  const x = (v) => mx + ((v - dMin) / (dMax - dMin)) * (width - 2 * mx);
  const yc = 26;
  let s = `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" style="display:block;width:100%;height:auto;" role="img" aria-label="Placebo effects of the control cells with the area marked">`;
  s += `<line x1="${mx}" y1="${yc}" x2="${width - mx}" y2="${yc}" stroke="var(--rule)" stroke-width="1" shape-rendering="crispEdges"/>`;
  s += `<line x1="${x(0)}" y1="${yc - 12}" x2="${x(0)}" y2="${yc + 12}" stroke="var(--ink)" stroke-width="1" opacity="0.5" shape-rendering="crispEdges"/>`;
  s += `<text x="${x(0)}" y="${yc + 28}" text-anchor="middle" font-size="12" fill="var(--muted)" class="num">0</text>`;
  effects.forEach((v) => {
    if (!Number.isFinite(v)) return;
    s += `<line x1="${x(v)}" y1="${yc - 6}" x2="${x(v)}" y2="${yc + 6}" stroke="var(--muted)" stroke-width="1" opacity="0.6"/>`;
  });
  if (Number.isFinite(point)) {
    s += `<circle cx="${x(point)}" cy="${yc}" r="5.5" fill="var(${colorVar})" stroke="var(--paper)" stroke-width="1.5"/>`;
    const anchor = x(point) > width * 0.85 ? "end" : x(point) < width * 0.15 ? "start" : "middle";
    // if the area sits on top of the zero label, put its label above the axis instead
    const ly = Math.abs(x(point) - x(0)) < 48 ? yc - 16 : yc + 28;
    s += `<text x="${x(point)}" y="${ly}" text-anchor="${anchor}" font-size="12" fill="var(${colorVar})" class="num">area ${fmtNum(signal, point, { sign: true })}</text>`;
  }
  s += "</svg>";
  return s;
}
