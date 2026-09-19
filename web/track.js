// Otherwise — track record page.
import {
  apiGet, fmtSignalValue, VERDICT_LABEL, SIGNAL_LABEL, CHANGE_TYPE_LABEL, initHowItWorksDrawer, renderFooter,
} from "./common.js";

const contentEl = document.getElementById("content");

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function summaryLine(summary) {
  const parts = [];
  if (summary.n !== undefined) parts.push(`${summary.n} sites`);
  if (summary.hits !== undefined) parts.push(`${summary.hits} correct`);
  if (summary.false_alarms !== undefined) parts.push(`${summary.false_alarms} false alarms`);
  if (summary.cant_tell !== undefined) parts.push(`${summary.cant_tell} can't tell`);
  return parts.join(" · ");
}

function renderRow(r) {
  const statusLabel = VERDICT_LABEL[r.status] || r.status || "—";
  const effect = (r.effect !== undefined && r.effect !== null && r.signal)
    ? `${fmtSignalValue(r.signal, r.effect, { sign: true })}${r.lo !== undefined && r.hi !== undefined ? ` (${fmtSignalValue(r.signal, r.lo, { sign: true })} to ${fmtSignalValue(r.signal, r.hi, { sign: true })})` : ""}`
    : "—";
  return `
    <tr>
      <td><a href="/v/${encodeURIComponent(r.id)}">${escapeHtml(r.label || r.id)}</a></td>
      <td>${escapeHtml(CHANGE_TYPE_LABEL[r.type] || r.type || "—")}</td>
      <td>${escapeHtml(r.expected || "—")}</td>
      <td class="verdict-cell v-${r.status}">${statusLabel}</td>
      <td class="tnum">${effect}</td>
      <td>${escapeHtml(r.signal ? (SIGNAL_LABEL[r.signal] || r.signal) : "—")}</td>
      <td>${r.source ? `<a href="${escapeHtml(r.source)}" target="_blank" rel="noopener">source</a>` : "—"}</td>
    </tr>`;
}

async function boot() {
  let data;
  try {
    data = await apiGet("/api/track-record");
  } catch (err) {
    contentEl.innerHTML = `<div class="error-state"><p class="muted">Could not load the track record.</p></div>`;
    return;
  }

  if (!data.summary) {
    contentEl.innerHTML = `
      <section class="page-head">
        <h1>Track record</h1>
        <p>No validation runs yet.</p>
      </section>`;
  } else {
    const rows = (data.runs || []).map(renderRow).join("");
    contentEl.innerHTML = `
      <section class="page-head">
        <h1>Track record</h1>
        <p>Every known-answer site the tool has been run on, misses included. Expected answers come from the documented sources linked in each row.</p>
        <div class="summary-line tnum">${summaryLine(data.summary)}</div>
      </section>
      <div class="table-wrap">
        <table class="track-table">
          <thead>
            <tr><th>Site</th><th>Type</th><th>Expected</th><th>Verdict</th><th>Effect</th><th>Signal</th><th>Source</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  initHowItWorksDrawer();
  renderFooter(document.getElementById("site-footer"), { withHowItWorks: true });
}

// ---- blind validation --------------------------------------------------------
//
// The hand-picked known-answer table above is small and was chosen by us. This
// section reports the blind test: a seeded, scripted draw from public ground
// truth, run through the unchanged pipeline, plus blind human review of the
// same cases. Three deciders are reported separately -- tool alone, human
// alone, tool + human -- each with its own denominator and a 95% Wilson
// interval. Where there is no denominator, the page says so; it never prints a
// rate with nothing behind it.
//
// Data: GET /api/review/results (src/app/review.py). If that router is not
// mounted, this section does not appear at all.

const BLIND_STYLE = `
.blind { margin: 48px 0 72px; border-top: 1px solid var(--rule); padding-top: 18px; }
.blind h2 { font-size: 24px; font-weight: 600; letter-spacing: -0.01em; }
.blind .blind-sub { color: var(--muted); max-width: 660px; margin-top: 10px; font-size: 14px; }
.blind .three { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-top: 20px; }
@media (max-width: 760px) { .blind .three { grid-template-columns: 1fr; } }
.blind .card { border: 1px solid var(--rule); background: var(--panel); padding: 14px; }
.blind .card h3 { font-size: 13px; text-transform: uppercase; letter-spacing: .07em; color: var(--muted); font-weight: 500; }
.blind .card .who { font-size: 13px; color: var(--muted); margin-top: 4px; }
.blind .row { display: flex; justify-content: space-between; gap: 10px; border-top: 1px solid var(--rule); padding: 8px 0 6px; font-size: 14px; margin-top: 8px; }
.blind .row:first-of-type { margin-top: 12px; }
.blind .row .k { color: var(--muted); }
.blind .row .v { text-align: right; }
.blind .row .ci { display: block; font-size: 12px; color: var(--muted); }
.blind .protocol { margin-top: 20px; font-size: 13px; color: var(--muted); max-width: 720px; }
.blind .protocol dt { font-weight: 500; color: var(--ink); margin-top: 8px; }
.blind .none { font-size: 14px; margin-top: 12px; }
`;

function pctCI(r) {
  if (!r || !r.n) return { value: "not measured", ci: "no runs of this kind yet" };
  const pct = (100 * r.rate).toFixed(1);
  return {
    value: `${pct}% (${r.k} of ${r.n})`,
    ci: `95% CI ${(100 * r.lo).toFixed(1)}–${(100 * r.hi).toFixed(1)}%`,
  };
}

function blindRow(label, r) {
  const { value, ci } = pctCI(r);
  return `<div class="row"><span class="k">${escapeHtml(label)}</span><span class="v tnum">${escapeHtml(value)}<span class="ci">${escapeHtml(ci)}</span></span></div>`;
}

function blindCard(title, who, block, emptyNote) {
  if (!block || !block.n) {
    return `<div class="card"><h3>${escapeHtml(title)}</h3><p class="who">${escapeHtml(who)}</p>
      <p class="none">${escapeHtml(emptyNote)}</p></div>`;
  }
  return `<div class="card">
    <h3>${escapeHtml(title)}</h3>
    <p class="who">${escapeHtml(who)}</p>
    ${blindRow("Detected a real change", block.events.detection)}
    ${blindRow("Missed a real change", block.events.miss)}
    ${blindRow("Can't tell, on real changes", block.events.cant_tell)}
    ${blindRow("False alarm on a control", block.controls.false_alarm)}
    ${blindRow("Can't tell, on controls", block.controls.cant_tell)}
  </div>`;
}

async function renderBlind() {
  let d;
  try {
    d = await apiGet("/api/review/results");
  } catch (err) {
    return;                       // review router not mounted: no blind section
  }
  if (!document.getElementById("blind-style")) {
    const st = document.createElement("style");
    st.id = "blind-style";
    st.textContent = BLIND_STYLE;
    document.head.appendChild(st);
  }
  const sample = d.sample || {};
  const section = document.createElement("section");
  section.className = "blind";
  section.id = "blind-validation";

  const reviewed = d.reviews > 0;
  section.innerHTML = `
    <h2>Blind validation</h2>
    <p class="blind-sub">The table above is a small set of sites we chose ourselves. This is the blind test: events and no-change areas drawn mechanically from public ground truth with a fixed seed, run through the same pipeline, and reviewed by eye with the answers hidden. Nothing here is filtered after the fact.</p>
    <div class="three">
      ${blindCard("Tool alone", "The statistical verdict, no human involved.", d.tool,
                  "No blind run has finished yet.")}
      ${blindCard("Human alone", "A reviewer judging the imagery and charts with the answer hidden.", d.human,
                  "No blind reviews recorded yet.")}
      ${blindCard("Tool + human", "The tool decides; the human adjudicates its can't-tells.", d.tool_human,
                  "No blind reviews recorded yet, so there is nothing to combine.")}
    </div>
    <dl class="protocol">
      <dt>Combination rule</dt>
      <dd>${escapeHtml(d.combination_rule || "")}</dd>
      <dt>Sample</dt>
      <dd>Seed ${escapeHtml(String(sample.seed ?? "—"))}, ${escapeHtml(String(sample.sample_n ?? "—"))} items drawn, ${escapeHtml(String(sample.completed ?? "—"))} runs recorded${sample.sample_git_commit ? `, drawn at commit ${escapeHtml(String(sample.sample_git_commit))}` : ""}${sample.git_commit ? `, scored at commit ${escapeHtml(String(sample.git_commit))}` : ""}. Ground truth: Hansen Global Forest Change loss year and MTBS burned-area perimeters. Full protocol, per-item results and the sources that were considered and not used are in <a href="https://github.com/Mohib314159/carbon-twin/blob/main/docs/BLIND_VALIDATION.md" target="_blank" rel="noopener">docs/BLIND_VALIDATION.md</a>.</dd>
      <dt>Intervals</dt>
      <dd>${escapeHtml(d.interval || "95% Wilson score interval")}. Every rate is shown with the number of cases behind it; a rate with no cases behind it is printed as “not measured”.</dd>
      <dt>Human review</dt>
      <dd>${reviewed
        ? `${escapeHtml(String(d.reviews))} blind judgements from ${escapeHtml(String(d.reviewers))} reviewer${d.reviewers === 1 ? "" : "s"}, over ${escapeHtml(String(d.cases_prepared_for_review))} cases prepared for review.`
        : `No blind reviews have been recorded yet. ${escapeHtml(String(d.cases_prepared_for_review))} cases are prepared for review; the human and tool + human columns will stay empty until someone reviews them.`}
        <a href="/review">Review cases</a>.</dd>
    </dl>`;
  contentEl.appendChild(section);
}

boot().finally(renderBlind);
