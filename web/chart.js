// Otherwise — dependency-free inline SVG charts for the verdict page.
import { fmtSignalValue } from "./common.js";

const SVGNS = "http://www.w3.org/2000/svg";
const MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

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
  const start = new Date(tMin);
  let y = start.getUTCFullYear();
  let m = start.getUTCMonth();
  // snap to the first tick at or after tMin on the step grid
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

/**
 * Draws the primary trajectory chart: treated vs counterfactual, placebo
 * band, event line, post-event tint. `container` is cleared and filled with
 * a fresh <svg>. Safe to call again (e.g. on resize) with the same args.
 */
export function drawTrajectoryChart(container, chart, { eventDate, signal }) {
  const width = Math.max(container.clientWidth || 640, 280);
  const height = 340;
  const margin = { top: 20, right: 16, bottom: 30, left: 56 };
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

  const svg = svgEl("svg", { width, height, viewBox: `0 0 ${width} ${height}`, style: "display:block;width:100%;height:auto;" });

  // post-event tint
  if (eventT < tMax) {
    svg.appendChild(svgEl("rect", {
      x: x(eventT), y: margin.top, width: Math.max(x(tMax) - x(eventT), 0),
      height: height - margin.top - margin.bottom, fill: "rgba(0,0,0,0.03)",
    }));
  }

  // y gridlines + labels
  const ticks = yTicks(yMin, yMax, 5);
  for (const t of ticks) {
    const ty = y(t);
    svg.appendChild(svgEl("line", { x1: margin.left, x2: width - margin.right, y1: ty, y2: ty, stroke: "var(--rule)", "stroke-width": 1 }));
    const lbl = svgEl("text", { x: margin.left - 8, y: ty + 4, "text-anchor": "end", class: "num", "font-size": 11, fill: "var(--muted)" });
    lbl.textContent = fmtSignalValue(signal, t);
    svg.appendChild(lbl);
  }

  // x ticks
  for (const t of xTicks(tMin, tMax, Math.max(3, Math.floor(width / 110)))) {
    const tx = x(t);
    const lbl = svgEl("text", { x: tx, y: height - margin.bottom + 18, "text-anchor": "middle", "font-size": 11, fill: "var(--muted)" });
    lbl.textContent = xTickLabel(t);
    svg.appendChild(lbl);
  }

  // placebo band (fill between bandLo and bandHi)
  let bandPath = `M${x(times[0])},${y(bandHi[0])}`;
  for (let i = 1; i < times.length; i++) bandPath += ` L${x(times[i])},${y(bandHi[i])}`;
  for (let i = times.length - 1; i >= 0; i--) bandPath += ` L${x(times[i])},${y(bandLo[i])}`;
  bandPath += " Z";
  svg.appendChild(svgEl("path", { d: bandPath, fill: "var(--band)", stroke: "none" }));

  // counterfactual (dashed)
  svg.appendChild(svgEl("path", { d: linePath(times, chart.counterfactual, x, y), fill: "none", stroke: "var(--counter)", "stroke-width": 1.6, "stroke-dasharray": "5,4" }));

  // treated (solid) + dots at real observations
  svg.appendChild(svgEl("path", { d: linePath(times, chart.treated, x, y), fill: "none", stroke: "var(--treated)", "stroke-width": 1.6 }));
  for (let i = 0; i < times.length; i++) {
    if (chart.n_obs && chart.n_obs[i] > 0) {
      svg.appendChild(svgEl("circle", { cx: x(times[i]), cy: y(chart.treated[i]), r: 2.4, fill: "var(--treated)" }));
    }
  }

  // event line + label
  if (eventT >= tMin && eventT <= tMax) {
    const ex = x(eventT);
    svg.appendChild(svgEl("line", { x1: ex, x2: ex, y1: margin.top, y2: height - margin.bottom, stroke: "var(--event)", "stroke-width": 1.2 }));
    const lbl = svgEl("text", { x: ex + 4, y: margin.top + 10, "font-size": 11, fill: "var(--event)" });
    lbl.textContent = "event";
    svg.appendChild(lbl);
  }

  // hover crosshair (hidden by default)
  const hoverLine = svgEl("line", { x1: 0, x2: 0, y1: margin.top, y2: height - margin.bottom, stroke: "var(--ink)", "stroke-width": 1, opacity: 0 });
  const hoverDotT = svgEl("circle", { r: 3.2, fill: "var(--treated)", opacity: 0 });
  const hoverDotC = svgEl("circle", { r: 3.2, fill: "var(--counter)", opacity: 0 });
  svg.appendChild(hoverLine); svg.appendChild(hoverDotT); svg.appendChild(hoverDotC);

  const hitRect = svgEl("rect", { x: margin.left, y: margin.top, width: width - margin.left - margin.right, height: height - margin.top - margin.bottom, fill: "transparent" });
  svg.appendChild(hitRect);

  wrap.appendChild(svg);
  const tip = getOrMakeTooltip(wrap);

  hitRect.addEventListener("mousemove", (e) => {
    const rect = svg.getBoundingClientRect();
    const scaleX = width / rect.width;
    const px = (e.clientX - rect.left) * scaleX;
    const t = (px - margin.left) / (width - margin.left - margin.right) * (tMax - tMin) + tMin;
    const i = nearestIndex(times, t);
    const cx = x(times[i]);
    hoverLine.setAttribute("x1", cx); hoverLine.setAttribute("x2", cx); hoverLine.setAttribute("opacity", 1);
    hoverDotT.setAttribute("cx", cx); hoverDotT.setAttribute("cy", y(chart.treated[i])); hoverDotT.setAttribute("opacity", 1);
    hoverDotC.setAttribute("cx", cx); hoverDotC.setAttribute("cy", y(chart.counterfactual[i])); hoverDotC.setAttribute("opacity", 1);
    const gap = chart.treated[i] - chart.counterfactual[i];
    tip.innerHTML = `${tooltipDate(times[i])}<br>Area: ${fmtSignalValue(signal, chart.treated[i])}<br>Counterfactual: ${fmtSignalValue(signal, chart.counterfactual[i])}<br>Gap: ${fmtSignalValue(signal, gap, { sign: true })}`;
    tip.style.display = "block";
    tip.style.left = `${(cx / width) * 100}%`;
    tip.style.top = `${(y(chart.treated[i]) / height) * 100}%`;
  });
  hitRect.addEventListener("mouseleave", () => {
    tip.style.display = "none";
    hoverLine.setAttribute("opacity", 0);
    hoverDotT.setAttribute("opacity", 0);
    hoverDotC.setAttribute("opacity", 0);
  });
}

/** The secondary gap (effect) chart: effect vs. zero, with its placebo band. */
export function drawGapChart(container, chart, { eventDate, signal }) {
  const width = Math.max(container.clientWidth || 640, 280);
  const height = 160;
  const margin = { top: 14, right: 16, bottom: 26, left: 56 };
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

  const svg = svgEl("svg", { width, height, viewBox: `0 0 ${width} ${height}`, style: "display:block;width:100%;height:auto;" });

  if (eventT < tMax) {
    svg.appendChild(svgEl("rect", {
      x: x(eventT), y: margin.top, width: Math.max(x(tMax) - x(eventT), 0),
      height: height - margin.top - margin.bottom, fill: "rgba(0,0,0,0.03)",
    }));
  }

  const ticks = yTicks(yMin, yMax, 3);
  for (const t of ticks) {
    const ty = y(t);
    svg.appendChild(svgEl("line", { x1: margin.left, x2: width - margin.right, y1: ty, y2: ty, stroke: "var(--rule)", "stroke-width": 1 }));
    const lbl = svgEl("text", { x: margin.left - 8, y: ty + 4, "text-anchor": "end", class: "num", "font-size": 11, fill: "var(--muted)" });
    lbl.textContent = fmtSignalValue(signal, t, { sign: true });
    svg.appendChild(lbl);
  }
  for (const t of xTicks(tMin, tMax, Math.max(3, Math.floor(width / 110)))) {
    const tx = x(t);
    const lbl = svgEl("text", { x: tx, y: height - margin.bottom + 18, "text-anchor": "middle", "font-size": 11, fill: "var(--muted)" });
    lbl.textContent = xTickLabel(t);
    svg.appendChild(lbl);
  }

  // zero line
  svg.appendChild(svgEl("line", { x1: margin.left, x2: width - margin.right, y1: y(0), y2: y(0), stroke: "var(--ink)", "stroke-width": 1, opacity: 0.5 }));

  let bandPath = `M${x(times[0])},${y(bandHi[0])}`;
  for (let i = 1; i < times.length; i++) bandPath += ` L${x(times[i])},${y(bandHi[i])}`;
  for (let i = times.length - 1; i >= 0; i--) bandPath += ` L${x(times[i])},${y(bandLo[i])}`;
  bandPath += " Z";
  svg.appendChild(svgEl("path", { d: bandPath, fill: "var(--band)", stroke: "none" }));

  svg.appendChild(svgEl("path", { d: linePath(times, chart.effect, x, y), fill: "none", stroke: "var(--treated)", "stroke-width": 1.6 }));

  if (eventT >= tMin && eventT <= tMax) {
    const ex = x(eventT);
    svg.appendChild(svgEl("line", { x1: ex, x2: ex, y1: margin.top, y2: height - margin.bottom, stroke: "var(--event)", "stroke-width": 1.2 }));
  }

  const hoverLine = svgEl("line", { x1: 0, x2: 0, y1: margin.top, y2: height - margin.bottom, stroke: "var(--ink)", "stroke-width": 1, opacity: 0 });
  const hoverDot = svgEl("circle", { r: 3.2, fill: "var(--treated)", opacity: 0 });
  svg.appendChild(hoverLine); svg.appendChild(hoverDot);
  const hitRect = svgEl("rect", { x: margin.left, y: margin.top, width: width - margin.left - margin.right, height: height - margin.top - margin.bottom, fill: "transparent" });
  svg.appendChild(hitRect);

  wrap.appendChild(svg);
  const tip = getOrMakeTooltip(wrap);

  hitRect.addEventListener("mousemove", (e) => {
    const rect = svg.getBoundingClientRect();
    const scaleX = width / rect.width;
    const px = (e.clientX - rect.left) * scaleX;
    const t = (px - margin.left) / (width - margin.left - margin.right) * (tMax - tMin) + tMin;
    const i = nearestIndex(times, t);
    const cx = x(times[i]);
    hoverLine.setAttribute("x1", cx); hoverLine.setAttribute("x2", cx); hoverLine.setAttribute("opacity", 1);
    hoverDot.setAttribute("cx", cx); hoverDot.setAttribute("cy", y(chart.effect[i])); hoverDot.setAttribute("opacity", 1);
    tip.innerHTML = `${tooltipDate(times[i])}<br>Gap: ${fmtSignalValue(signal, chart.effect[i], { sign: true })}`;
    tip.style.display = "block";
    tip.style.left = `${(cx / width) * 100}%`;
    tip.style.top = `${(y(chart.effect[i]) / height) * 100}%`;
  });
  hitRect.addEventListener("mouseleave", () => {
    tip.style.display = "none";
    hoverLine.setAttribute("opacity", 0);
    hoverDot.setAttribute("opacity", 0);
  });
}

function linePath(times, values, x, y) {
  let d = "";
  for (let i = 0; i < times.length; i++) {
    if (!Number.isFinite(values[i])) continue;
    d += (d ? " L" : "M") + `${x(times[i])},${y(values[i])}`;
  }
  return d;
}
