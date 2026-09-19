// Otherwise — mobile layout behaviour (landing page only).
//
// Attaches to the EXISTING DOM from the outside: this file never imports or
// calls into landing.js, and never assumes anything about it beyond the
// element ids/classes already in index.html. It only runs its sheet logic
// while the viewport is <=640px wide (matching mobile.css's media query),
// so it never touches the desktop layout.

const MOBILE = window.matchMedia("(max-width: 640px)");

const sheet = document.getElementById("side-panel");
if (sheet) initSheet(sheet);

function initSheet(sheet) {
  const handle = document.getElementById("sheet-handle");
  const wordmark = sheet.querySelector(":scope > h1");
  const tagline = sheet.querySelector(":scope > .tagline");
  const dragChrome = [handle, wordmark, tagline].filter(Boolean);
  const drawBtn = document.getElementById("draw-btn");
  const runForm = document.getElementById("run-form");
  const progressBlock = document.getElementById("progress-block");

  const SNAPS = ["full", "half", "peek"]; // top -> bottom; index also used for flick direction
  const PEEK_PX = 120;

  let active = MOBILE.matches;
  let current = "half"; // landing page starts at half, per spec
  let raf = null;

  // ---- geometry -----------------------------------------------------------

  function heights() {
    const vh = window.innerHeight;
    return { full: vh * 0.92, half: vh * 0.55, peek: PEEK_PX };
  }

  function dFor(snap) {
    const h = heights();
    return Math.max(0, h.full - h[snap]);
  }

  // ---- applying a snap point ------------------------------------------------

  function applySnap(snap, { animate = true } = {}) {
    if (!active || !SNAPS.includes(snap)) return;
    current = snap;
    const h = heights();
    sheet.style.height = `${h.full}px`;
    sheet.classList.remove("sheet-peek", "sheet-half", "sheet-full");
    sheet.classList.add(`sheet-${snap}`);
    if (snap !== "full") sheet.scrollTop = 0;
    document.documentElement.style.setProperty("--sheet-visible", `${h[snap]}px`);
    if (!animate) {
      sheet.classList.add("sheet-dragging"); // reuses the "kill transition" rule
      sheet.style.transform = `translateY(${dFor(snap)}px)`;
      // force a reflow so the next class removal doesn't get batched with this write
      void sheet.offsetHeight;
      sheet.classList.remove("sheet-dragging");
    } else {
      sheet.style.transform = `translateY(${dFor(snap)}px)`;
    }
  }

  function setTransformPx(d) {
    document.documentElement.style.setProperty("--sheet-visible", `${heights().full - d}px`);
    sheet.style.transform = `translateY(${d}px)`;
  }

  // ---- activate / deactivate on breakpoint crossing --------------------------

  function activate() {
    if (active) return;
    active = true;
    document.documentElement.style.setProperty("--sheet-visible", `${heights()[current]}px`);
    applySnap(current, { animate: false });
  }

  function deactivate() {
    if (!active) return;
    active = false;
    document.body.classList.remove("sheet-dragging");
    sheet.classList.remove("sheet-dragging", "sheet-peek", "sheet-half", "sheet-full");
    sheet.style.transform = "";
    sheet.style.height = "";
    sheet.scrollTop = 0;
    document.documentElement.style.removeProperty("--sheet-visible");
  }

  MOBILE.addEventListener
    ? MOBILE.addEventListener("change", (e) => (e.matches ? activate() : deactivate()))
    : MOBILE.addListener((e) => (e.matches ? activate() : deactivate())); // Safari <14

  window.addEventListener("resize", () => {
    if (!active) return;
    if (raf) cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => applySnap(current, { animate: false }));
  });

  // ---- dragging --------------------------------------------------------------
  //
  // Two kinds of drag surface:
  //  - "chrome" (the handle, wordmark, tagline): always starts a sheet drag.
  //  - the rest of the sheet (its scrollable content): starts a sheet drag
  //    only when there's nothing to scroll (snap !== "full") or the content
  //    is already scrolled to the top and the gesture moves downward —
  //    otherwise it's left alone so native scrolling happens.

  let dragging = false;
  let pendingFromContent = false;
  let startY = 0;
  let startD = 0;
  let startSnap = "half";
  let samples = []; // {t, y} of the last ~80ms, for release velocity

  function onDragStart(clientY, fromChrome) {
    if (!active) return;
    startY = clientY;
    startD = dFor(current);
    startSnap = current;
    samples = [{ t: performance.now(), y: clientY }];
    if (fromChrome) {
      beginDrag();
    } else {
      pendingFromContent = true;
      dragging = false;
    }
  }

  function beginDrag() {
    dragging = true;
    pendingFromContent = false;
    sheet.classList.add("sheet-dragging");
    document.body.classList.add("sheet-dragging");
  }

  function onDragMove(clientY, cancel) {
    if (!active) return false;
    const deltaY = clientY - startY;

    if (!dragging) {
      if (!pendingFromContent) return false;
      if (Math.abs(deltaY) < 6) return false; // ignore jitter/taps
      const atTop = sheet.scrollTop <= 0;
      const collapsibleFromFull = current === "full" && atTop && deltaY > 0;
      const noInternalScroll = current !== "full";
      if (!(collapsibleFromFull || noInternalScroll)) {
        pendingFromContent = false; // let the browser scroll natively
        return false;
      }
      beginDrag();
    }

    samples.push({ t: performance.now(), y: clientY });
    while (samples.length > 6) samples.shift();

    const h = heights();
    const minD = 0; // full
    const maxD = dFor("peek");
    const d = Math.min(maxD, Math.max(minD, startD + deltaY));
    setTransformPx(d);
    cancel();
    return true;
  }

  function velocity() {
    if (samples.length < 2) return 0;
    const now = samples[samples.length - 1];
    let old = samples[0];
    for (const s of samples) {
      if (now.t - s.t <= 80) { old = s; break; }
    }
    const dt = now.t - old.t;
    if (dt <= 0) return 0;
    return (now.y - old.y) / dt; // px/ms; positive = moving down
  }

  function onDragEnd() {
    if (!dragging) { pendingFromContent = false; return; }
    dragging = false;
    sheet.classList.remove("sheet-dragging");
    document.body.classList.remove("sheet-dragging");

    const v = velocity();
    const FLICK = 0.5; // px/ms
    let target;
    if (Math.abs(v) > FLICK) {
      const dir = v > 0 ? 1 : -1; // down collapses toward peek, up expands toward full
      const idx = SNAPS.indexOf(startSnap);
      target = SNAPS[Math.min(SNAPS.length - 1, Math.max(0, idx + dir))];
    } else {
      const curD = dFor(current); // current transform was left mid-drag; read from style instead
      const currentPx = parseFloat(sheet.style.transform.replace(/[^0-9.-]/g, "")) || curD;
      target = SNAPS.reduce((best, s) => (
        Math.abs(dFor(s) - currentPx) < Math.abs(dFor(best) - currentPx) ? s : best
      ), SNAPS[0]);
    }
    applySnap(target);
  }

  // -- pointer events (mouse + touch + pen, and how this is tested with a
  //    mouse) with a touch-event fallback for engines without them.
  const usePointer = typeof window.PointerEvent === "function";

  function wireChrome(el) {
    if (usePointer) {
      el.addEventListener("pointerdown", (e) => {
        if (!active) return;
        onDragStart(e.clientY, true);
        try { el.setPointerCapture(e.pointerId); } catch (_) { /* ignore */ }
      });
      el.addEventListener("pointermove", (e) => { if (dragging) onDragMove(e.clientY, () => e.preventDefault()); });
      el.addEventListener("pointerup", onDragEnd);
      el.addEventListener("pointercancel", onDragEnd);
    } else {
      el.addEventListener("touchstart", (e) => { if (active) onDragStart(e.touches[0].clientY, true); }, { passive: true });
      el.addEventListener("touchmove", (e) => { if (dragging) onDragMove(e.touches[0].clientY, () => e.preventDefault()); }, { passive: false });
      el.addEventListener("touchend", onDragEnd);
      el.addEventListener("touchcancel", onDragEnd);
    }
  }

  function wireContent(el) {
    if (usePointer) {
      el.addEventListener("pointerdown", (e) => {
        if (!active || dragChrome.includes(e.target)) return;
        onDragStart(e.clientY, false);
      });
      el.addEventListener("pointermove", (e) => {
        if (!active) return;
        const handled = onDragMove(e.clientY, () => e.preventDefault());
        if (handled) { try { el.setPointerCapture(e.pointerId); } catch (_) { /* ignore */ } }
      });
      el.addEventListener("pointerup", onDragEnd);
      el.addEventListener("pointercancel", onDragEnd);
    } else {
      el.addEventListener("touchstart", (e) => {
        if (!active || dragChrome.includes(e.target)) return;
        onDragStart(e.touches[0].clientY, false);
      }, { passive: true });
      el.addEventListener("touchmove", (e) => { onDragMove(e.touches[0].clientY, () => e.preventDefault()); }, { passive: false });
      el.addEventListener("touchend", onDragEnd);
      el.addEventListener("touchcancel", onDragEnd);
    }
  }

  dragChrome.forEach(wireChrome);
  wireContent(sheet);

  // ---- react to the rest of the landing page, without editing it -------------

  if (drawBtn) {
    drawBtn.addEventListener("click", () => { if (active) applySnap("peek"); });
  }

  if (runForm) {
    const mo = new MutationObserver(() => {
      if (active && runForm.style.display !== "none") applySnap("half");
    });
    mo.observe(runForm, { attributes: true, attributeFilter: ["style"] });
  }

  if (progressBlock) {
    const mo = new MutationObserver(() => {
      if (active && progressBlock.style.display !== "none") applySnap("peek");
    });
    mo.observe(progressBlock, { attributes: true, attributeFilter: ["style"] });
  }

  // ---- initial paint -----------------------------------------------------
  if (active) applySnap(current, { animate: false });
}
