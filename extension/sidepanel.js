const DEFAULT_URL = "http://127.0.0.1:8000";
const STORAGE_KEY = "comps_server_url";

const frame = document.getElementById("app-frame");
const drawer = document.getElementById("settings-drawer");
const urlInput = document.getElementById("server-url");
const msgEl = document.getElementById("settings-msg");
const offlineBanner = document.getElementById("offline-banner");
const offlineUrl = document.getElementById("offline-url");

let currentUrl = DEFAULT_URL;

function normalizeUrl(raw) {
  const trimmed = (raw || "").trim().replace(/\/+$/, "");
  if (!trimmed) return DEFAULT_URL;
  if (!/^https?:\/\//i.test(trimmed)) return "http://" + trimmed;
  return trimmed;
}

function loadSavedUrl(cb) {
  if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.sync) {
    chrome.storage.sync.get([STORAGE_KEY], (res) => {
      cb(normalizeUrl(res[STORAGE_KEY] || DEFAULT_URL));
    });
  } else {
    cb(normalizeUrl(localStorage.getItem(STORAGE_KEY) || DEFAULT_URL));
  }
}

function saveUrl(url, cb) {
  if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.sync) {
    chrome.storage.sync.set({ [STORAGE_KEY]: url }, cb);
  } else {
    localStorage.setItem(STORAGE_KEY, url);
    if (cb) cb();
  }
}

async function connect(url) {
  currentUrl = normalizeUrl(url);
  urlInput.value = currentUrl;
  offlineUrl.textContent = currentUrl;
  offlineBanner.hidden = true;

  // Quick reachability check so we can show a clear helper if the local server isn't running.
  try {
    await fetch(currentUrl + "/", { mode: "no-cors", cache: "no-store" });
    frame.src = currentUrl + "/";
  } catch {
    offlineBanner.hidden = false;
  }
}

document.getElementById("btn-reload").addEventListener("click", () => {
  connect(currentUrl);
});

document.getElementById("btn-retry").addEventListener("click", () => {
  connect(currentUrl);
});

document.getElementById("btn-popout").addEventListener("click", () => {
  window.open(currentUrl + "/", "_blank", "noopener");
});

document.getElementById("btn-settings").addEventListener("click", () => {
  drawer.hidden = !drawer.hidden;
  msgEl.hidden = true;
});

document.getElementById("btn-save-url").addEventListener("click", () => {
  const next = normalizeUrl(urlInput.value);
  saveUrl(next, () => {
    msgEl.textContent = "Saved and connecting to " + next;
    msgEl.hidden = false;
    connect(next);
    setTimeout(() => {
      drawer.hidden = true;
      msgEl.hidden = true;
    }, 800);
  });
});

document.querySelectorAll(".ext-preset").forEach((btn) => {
  btn.addEventListener("click", () => {
    urlInput.value = btn.dataset.url;
    document.getElementById("btn-save-url").click();
  });
});

loadSavedUrl((saved) => connect(saved));
