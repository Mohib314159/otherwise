// Otherwise — blind review. A research instrument, not the product's hero.
//
// The reviewer sees the imagery, the time-lapse and the two charts for one
// sampled area at a time, in a per-session random order, and answers
// changed / not changed / unsure. Nothing on this page says what the area is,
// where it is, when the claimed event was, or what the tool concluded: the
// server's /api/review/next payload does not contain any of it (see
// src/app/review.py and tests/test_app_review.py).
import { apiGet, apiPost, renderFooter } from "./common.js";

const contentEl = document.getElementById("content");
const STORE_KEY = "otherwise.review.session";
const ANSWER_LABELS = [
  ["changed", "Changed", "1"],
  ["not_changed", "Not changed", "2"],
  ["unsure", "Unsure", "3"],
];

let state = { sessionId: null, case: null, answer: null, confidence: "", shownAt: 0, busy: false };

function el(tag, attrs = {}, children = []) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else n.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c) n.appendChild(c);
  return n;
}

function svgEl(tag, attrs = {}) {
  const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) n.setAttribute(k, v);
  return n;
}

/** Minimal line chart on a relative-day axis. series: [{values, color, dash}]. */
function lineChart(days, series, { height = 180, zeroLine = false, label = "" } = {}) {
  const W = 420, H = height, m = { t: 8, r: 8, b: 22, l: 34 };
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": label || "chart" });
  const pts = [];
  for (const s of series) for (const v of s.values || []) if (v !== null && Number.isFinite(v)) pts.push(v);
  if (!days || !days.length || !pts.length) {
    svg.appendChild(svgEl("line", { x1: m.l, y1: H - m.b, x2: W - m.r, y2: H - m.b, stroke: "var(--rule)" }));
    return svg;
  }
  const xs = days, x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...pts), y1 = Math.max(...pts);
  if (zeroLine) { y0 = Math.min(y0, 0); y1 = Math.max(y1, 0); }
  if (y1 - y0 < 1e-9) { y0 -= 0.5; y1 += 0.5; }
  const pad = (y1 - y0) * 0.08;
  y0 -= pad; y1 += pad;
  const X = (d) => m.l + ((d - x0) / Math.max(1, x1 - x0)) * (W - m.l - m.r);
  const Y = (v) => m.t + (1 - (v - y0) / (y1 - y0)) * (H - m.t - m.b);

  // axes: a hairline baseline and the event marker at day 0
  svg.appendChild(svgEl("line", { x1: m.l, y1: H - m.b, x2: W - m.r, y2: H - m.b, stroke: "var(--rule)" }));
  if (x0 <= 0 && x1 >= 0) {
    svg.appendChild(svgEl("line", { x1: X(0), y1: m.t, x2: X(0), y2: H - m.b, stroke: "var(--event)", "stroke-dasharray": "3 3" }));
  }
  if (zeroLine && y0 <= 0 && y1 >= 0) {
    svg.appendChild(svgEl("line", { x1: m.l, y1: Y(0), x2: W - m.r, y2: Y(0), stroke: "var(--rule)" }));
  }
  for (const s of series) {
    let d = "", open = false;
    (s.values || []).forEach((v, i) => {
      if (v === null || !Number.isFinite(v)) { open = false; return; }
      d += `${open ? "L" : "M"}${X(xs[i]).toFixed(1)} ${Y(v).toFixed(1)} `;
      open = true;
    });
    if (d) svg.appendChild(svgEl("path", { d, fill: "none", stroke: s.color, "stroke-width": s.width || 1.5, "stroke-dasharray": s.dash || null }));
  }
  for (const [d, anchor] of [[x0, "start"], [x1, "end"]]) {
    const t = svgEl("text", { x: X(d), y: H - 7, "text-anchor": anchor, fill: "var(--muted)", "font-size": "10" });
    t.textContent = `day ${d > 0 ? "+" : ""}${d}`;
    svg.appendChild(t);
  }
  for (const v of [y0 + pad, y1 - pad]) {
    const t = svgEl("text", { x: m.l - 5, y: Y(v) + 3, "text-anchor": "end", fill: "var(--muted)", "font-size": "10" });
    t.textContent = v.toFixed(2);
    svg.appendChild(t);
  }
  return svg;
}

function legend(items) {
  const wrap = el("div", { class: "legend" });
  items.forEach(([color, dash, text], i) => {
    const sw = el("span", { class: "swatch" });
    sw.style.background = dash ? "transparent" : color;
    if (dash) sw.style.borderTop = `2px dashed ${color}`;
    wrap.appendChild(sw);
    wrap.appendChild(document.createTextNode(text + (i < items.length - 1 ? "   " : "")));
  });
  return wrap;
}

function imagePane(title, url, caption) {
  const fig = el("figure", { class: "pane" }, [el("h3", { text: title })]);
  const img = el("img", { src: url, alt: title, loading: "eager" });
  img.addEventListener("error", () => { img.replaceWith(el("p", { class: "muted small", text: "Image unavailable." })); });
  fig.appendChild(img);
  if (caption) fig.appendChild(el("figcaption", { text: caption }));
  return fig;
}

function framesPane(frames) {
  if (!frames || frames.length < 2) return null;
  const box = el("div", { class: "frames" }, [el("h3", { class: "label", text: "Time-lapse" })]);
  const img = el("img", { src: frames[0].url, alt: "Time-lapse frame" });
  const day = el("span", { class: "day tnum", text: dayLabel(frames[0].day) });
  const slider = el("input", { type: "range", min: "0", max: String(frames.length - 1), value: "0",
    "aria-label": "Time-lapse frame" });
  slider.addEventListener("input", () => {
    const f = frames[Number(slider.value)];
    img.src = f.url;
    day.textContent = dayLabel(f.day);
  });
  box.appendChild(img);
  box.appendChild(el("div", { class: "frames-row" }, [day, slider]));
  return box;
}

function dayLabel(d) {
  return `day ${d > 0 ? "+" : ""}${d}`;
}

function chartPane(title, svg, legendItems, caption) {
  const box = el("div", { class: "chartbox" }, [el("h3", { text: title })]);
  box.appendChild(svg);
  if (legendItems) box.appendChild(legend(legendItems));
  if (caption) box.appendChild(el("p", { class: "legend", text: caption }));
  return box;
}

function renderIntro(nCases) {
  contentEl.replaceChildren();
  const head = el("section", { class: "review-head" }, [
    el("h1", { text: "Blind review" }),
    el("p", { text: "Judge each area by eye. You are shown the imagery, the time-lapse and the two charts for one sampled area at a time, in random order. You are not told where it is, what was claimed, or what the tool concluded." }),
  ]);
  const ul = el("ul");
  [
    "Answer changed if you can see a real surface change in this area around day 0, not a seasonal or weather difference.",
    "Answer not changed if the area looks the same before and after, allowing for season, haze and illumination.",
    "Answer unsure whenever you genuinely cannot tell. Unsure is a useful answer here; guessing is not.",
    "Once answered, a case is not shown again in this session. Your answers are stored against a session id, not your name.",
  ].forEach((t) => ul.appendChild(el("li", { text: t })));
  head.appendChild(ul);
  head.appendChild(el("p", { class: "small muted",
    text: nCases ? `${nCases} case${nCases === 1 ? "" : "s"} are prepared for review.`
                 : "No cases are prepared for review yet." }));

  const name = el("input", { type: "text", placeholder: "Your name or initials (optional)", "aria-label": "Reviewer name" });
  const start = el("button", { class: "btn", type: "button", text: nCases ? "Start reviewing" : "Nothing to review" });
  if (!nCases) start.setAttribute("disabled", "disabled");
  start.addEventListener("click", async () => {
    start.setAttribute("disabled", "disabled");
    try {
      const s = await apiPost("/api/review/session", { reviewer: name.value.slice(0, 80) });
      state.sessionId = s.session_id;
      try { localStorage.setItem(STORE_KEY, s.session_id); } catch (_) { /* private mode */ }
      await loadNext();
    } catch (err) {
      start.removeAttribute("disabled");
      head.appendChild(el("p", { class: "small", text: `Could not start a session: ${err.message}` }));
    }
  });
  head.appendChild(el("div", { class: "review-start" }, [name, start]));
  contentEl.appendChild(head);
}

function renderDone(answered) {
  contentEl.replaceChildren();
  contentEl.appendChild(el("section", { class: "review-done" }, [
    el("h2", { text: "That is every case." }),
    el("p", { class: "muted", text: `${answered} answered in this session. The numbers are on the track record page.` }),
    el("p", { class: "small muted", text: "Thank you — this is the reference data the tool is scored against." }),
  ]));
}

function renderCase(payload, answered, total) {
  state.case = payload;
  state.answer = null;
  state.confidence = "";
  state.shownAt = Date.now();
  contentEl.replaceChildren();

  const bar = el("div", { class: "review-bar" }, [
    el("div", { class: "progress tnum", text: `Case ${answered + 1} of ${total}` }),
    el("div", { class: "meta tnum", text: `${payload.area_ha} ha · ${payload.n_observations} clear observations` }),
  ]);
  contentEl.appendChild(bar);

  contentEl.appendChild(el("div", { class: "case-grid" }, [
    imagePane("Before", payload.images.before, "Clearest scene before day 0"),
    imagePane("After", payload.images.after, "Clearest scene after day 0"),
  ]));

  const fr = framesPane(payload.frames);
  if (fr) contentEl.appendChild(fr);

  const c = payload.chart || {};
  const traj = lineChart(c.day, [
    { values: c.observed, color: "var(--treated)", width: 1.6 },
    { values: c.control, color: "var(--counter)", dash: "4 3" },
  ], { label: "Observed and control trajectories" });
  const gap = lineChart(c.day, [
    { values: c.gap, color: "var(--treated)", width: 1.6 },
  ], { zeroLine: true, label: "Gap between observed and control" });
  contentEl.appendChild(el("div", { class: "charts" }, [
    chartPane("Trajectory", traj,
      [["var(--treated)", false, "this area"], ["var(--counter)", true, "control areas"]],
      payload.axis),
    chartPane("Gap", gap, null, "This area minus the control areas. Day 0 is the claimed date."),
  ]));

  // ---- answer ----
  const answerBox = el("section", { class: "answer" });
  answerBox.appendChild(el("h3", { class: "label", text: "Did this area change?" }));
  const row = el("div", { class: "answer-row" });
  const buttons = {};
  for (const [value, label, key] of ANSWER_LABELS) {
    const b = el("button", { class: "btn-answer", type: "button", "aria-pressed": "false" });
    b.appendChild(document.createTextNode(label));
    b.appendChild(el("kbd", { text: key }));
    b.addEventListener("click", () => pick(value));
    buttons[value] = b;
    row.appendChild(b);
  }
  answerBox.appendChild(row);

  const conf = el("div", { class: "conf" }, [el("span", { class: "muted", text: "Confidence (optional):" })]);
  for (const level of ["low", "medium", "high"]) {
    const id = `conf-${level}`;
    const input = el("input", { type: "radio", name: "confidence", id, value: level });
    input.addEventListener("change", () => { state.confidence = level; });
    conf.appendChild(el("label", { for: id }, [input, document.createTextNode(" " + level)]));
  }
  answerBox.appendChild(conf);

  const note = el("textarea", { rows: "2", placeholder: "Note (optional): what made you decide?", "aria-label": "Note" });
  answerBox.appendChild(note);

  const submit = el("button", { class: "btn", type: "button", text: "Submit and next" });
  submit.setAttribute("disabled", "disabled");
  const hint = el("span", { class: "hint", text: "Press 1, 2 or 3, then Enter." });
  answerBox.appendChild(el("div", { class: "submit-row" }, [submit, hint]));
  contentEl.appendChild(answerBox);

  function pick(value) {
    state.answer = value;
    for (const [v, b] of Object.entries(buttons)) b.setAttribute("aria-pressed", String(v === value));
    submit.removeAttribute("disabled");
  }

  async function send() {
    if (!state.answer || state.busy) return;
    state.busy = true;
    submit.setAttribute("disabled", "disabled");
    hint.textContent = "Saving…";
    try {
      await apiPost("/api/review/answer", {
        session_id: state.sessionId,
        case_id: payload.case_id,
        answer: state.answer,
        confidence: state.confidence,
        note: note.value.slice(0, 2000),
        seconds: Math.round((Date.now() - state.shownAt) / 100) / 10,
      });
      state.busy = false;
      await loadNext();
    } catch (err) {
      state.busy = false;
      submit.removeAttribute("disabled");
      hint.textContent = `Could not save: ${err.message}`;
    }
  }

  submit.addEventListener("click", send);
  document.onkeydown = (e) => {
    if (e.target && ["TEXTAREA", "INPUT"].includes(e.target.tagName) && e.key !== "Enter") return;
    if (e.key === "1") pick("changed");
    else if (e.key === "2") pick("not_changed");
    else if (e.key === "3") pick("unsure");
    else if (e.key === "Enter" && state.answer) { e.preventDefault(); send(); }
  };
}

async function loadNext() {
  contentEl.replaceChildren(el("div", { class: "loading-state", text: "Loading case…" }));
  let data;
  try {
    data = await apiGet(`/api/review/next?session=${encodeURIComponent(state.sessionId)}`);
  } catch (err) {
    if (err.status === 404) {                       // stale session id in localStorage
      try { localStorage.removeItem(STORE_KEY); } catch (_) { /* ignore */ }
      state.sessionId = null;
      return boot();
    }
    contentEl.replaceChildren(el("p", { class: "muted", text: `Could not load the next case: ${err.message}` }));
    return;
  }
  if (data.done || !data.case) renderDone(data.answered);
  else renderCase(data.case, data.answered, data.total);
}

async function boot() {
  renderFooter(document.getElementById("site-footer"));
  let stored = null;
  try { stored = localStorage.getItem(STORE_KEY); } catch (_) { /* private mode */ }
  if (stored) {
    state.sessionId = stored;
    return loadNext();
  }
  let n = 0;
  try {
    const r = await apiGet("/api/review/results");
    n = r.cases_prepared_for_review || 0;
  } catch (_) { /* show the intro anyway */ }
  renderIntro(n);
}

boot();
