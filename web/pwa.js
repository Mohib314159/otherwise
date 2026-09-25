// Otherwise — small PWA shell. No API responses or map tiles are cached.

const isStandalone = () => window.matchMedia?.("(display-mode: standalone)").matches || window.navigator.standalone === true;
const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
let installPrompt = null;

if (isStandalone()) document.body.classList.add("pwa-standalone");

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }, { once: true });
}

window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installPrompt = e;
  document.documentElement.classList.add("can-install-pwa");
});

window.addEventListener("appinstalled", () => {
  installPrompt = null;
  document.body.classList.add("pwa-standalone");
  closeInstallSheet();
});

function installSheet() {
  let sheet = document.getElementById("pwa-install-sheet");
  if (sheet) return sheet;
  sheet = document.createElement("div");
  sheet.id = "pwa-install-sheet";
  sheet.className = "pwa-sheet";
  sheet.setAttribute("aria-hidden", "true");
  sheet.innerHTML = `
    <button class="pwa-sheet-backdrop" type="button" data-pwa-close aria-label="Close install instructions"></button>
    <section class="pwa-sheet-card" role="dialog" aria-modal="true" aria-labelledby="pwa-title">
      <div class="pwa-sheet-handle" aria-hidden="true"></div>
      <button class="pwa-sheet-close" type="button" data-pwa-close aria-label="Close">×</button>
      <div class="pwa-app-icon"><span></span></div>
      <p class="pwa-kicker">Otherwise on your phone</p>
      <h2 id="pwa-title">Keep the map one tap away.</h2>
      <div class="pwa-ios-copy">
        <ol>
          <li><span class="pwa-step-no">1</span><span>Tap <strong>Share</strong> in Safari.</span></li>
          <li><span class="pwa-step-no">2</span><span>Choose <strong>Add to Home Screen</strong>.</span></li>
          <li><span class="pwa-step-no">3</span><span>Tap <strong>Add</strong>.</span></li>
        </ol>
      </div>
      <div class="pwa-generic-copy">
        <p>Install Otherwise from your browser for a full-screen map and faster return visits.</p>
        <button class="primary-action pwa-native-install" type="button">Install Otherwise</button>
      </div>
      <p class="pwa-foot">The app uses the same live site. Satellite data and verdicts are never stored offline.</p>
    </section>`;
  document.body.appendChild(sheet);
  sheet.querySelectorAll("[data-pwa-close]").forEach((el) => el.addEventListener("click", closeInstallSheet));
  sheet.querySelector(".pwa-native-install")?.addEventListener("click", triggerNativeInstall);
  return sheet;
}

function openInstallSheet() {
  if (isStandalone()) return;
  if (installPrompt && !isIOS) {
    triggerNativeInstall();
    return;
  }
  const sheet = installSheet();
  sheet.classList.toggle("is-ios", isIOS);
  sheet.classList.toggle("has-native", !!installPrompt && !isIOS);
  sheet.classList.add("open");
  sheet.setAttribute("aria-hidden", "false");
  document.body.classList.add("pwa-sheet-open");
}

function closeInstallSheet() {
  const sheet = document.getElementById("pwa-install-sheet");
  if (!sheet) return;
  sheet.classList.remove("open");
  sheet.setAttribute("aria-hidden", "true");
  document.body.classList.remove("pwa-sheet-open");
}

async function triggerNativeInstall() {
  if (!installPrompt) {
    openInstallSheet();
    return;
  }
  const prompt = installPrompt;
  installPrompt = null;
  try {
    await prompt.prompt();
    await prompt.userChoice;
  } catch (_) { /* browser owns the prompt; no app error needed */ }
}

document.querySelectorAll("[data-install-trigger]").forEach((el) => {
  if (isStandalone()) {
    el.hidden = true;
    return;
  }
  el.addEventListener("click", openInstallSheet);
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeInstallSheet();
});
