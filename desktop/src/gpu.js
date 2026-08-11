// ABOUTME: Installerer GPU-akselerasjon (torch med CUDA) på etterspurnad, med eit framdriftsvindauge.
// ABOUTME: Pakkane blir lagde i ei brukar-skrivbar mappe utanfor programmappa, sjå paths.gpuSiteDir().
"use strict";

const { BrowserWindow, app } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const { gpuSiteDir, resolvePython } = require("./paths");

const IS_WINDOWS = process.platform === "win32";
// Same CUDA-serie som setup.ps1 og README brukar for browser-appen.
const CUDA_INDEX_URL = "https://download.pytorch.org/whl/cu124";

/** GPU-pakkane er installerte når torch ligg i mappa. */
function isInstalled() {
  return fs.existsSync(path.join(gpuSiteDir(), "torch"));
}

/** Sjekkar om maskina har eit NVIDIA-kort, på same vis som setup.ps1: finst nvidia-smi? */
function hasNvidiaGpu() {
  return new Promise((resolve) => {
    const probe = spawn("nvidia-smi", ["-L"], { windowsHide: true });
    probe.once("error", () => resolve(false));
    probe.once("exit", (code) => resolve(code === 0));
  });
}

function settingsPath() {
  return path.join(app.getPath("userData"), "settings.json");
}

function readSettings() {
  try {
    return JSON.parse(fs.readFileSync(settingsPath(), "utf8"));
  } catch {
    return {};
  }
}

function updateSettings(patch) {
  const next = { ...readSettings(), ...patch };
  try {
    fs.mkdirSync(path.dirname(settingsPath()), { recursive: true });
    fs.writeFileSync(settingsPath(), JSON.stringify(next, null, 2), "utf8");
  } catch {
    /* innstillingar er ein bonus, ikkje kritisk */
  }
  return next;
}

function createProgressWindow(parent) {
  const window = new BrowserWindow({
    width: 640,
    height: 440,
    parent: parent ?? undefined,
    show: true,
    title: "Installerer GPU-akselerasjon",
    backgroundColor: "#0A3258",
    maximizable: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  window.setMenuBarVisibility(false);
  window.loadFile(path.join(__dirname, "gpu.html"));
  return window;
}

/**
 * Lastar ned og installerer torch med CUDA. Returnerer "installed", "cancelled" eller "failed".
 * Vindauget viser rå pip-utskrift, inkludert framdriftslinja for nedlastinga, som er viktig
 * her fordi nedlastinga er på fleire GB.
 */
function install(parentWindow, log) {
  const python = resolvePython();
  if (!python) {
    return Promise.resolve({ outcome: "failed", detail: "Fann ikkje Python-tolken." });
  }

  const target = gpuSiteDir();
  fs.mkdirSync(target, { recursive: true });

  const window = createProgressWindow(parentWindow);
  let pageReady = false;
  const pending = [];

  const flush = () => {
    while (pending.length && !window.isDestroyed()) {
      const chunk = pending.shift();
      window.webContents
        .executeJavaScript(`window.pushChunk(${JSON.stringify(chunk)})`)
        .catch(() => {});
    }
  };
  const send = (chunk) => {
    pending.push(chunk);
    if (pageReady) flush();
  };
  window.webContents.once("did-finish-load", () => {
    pageReady = true;
    flush();
  });

  // --no-cache-dir: hjulet er på fleire GB, og me vil ikkje bruke like mykje plass ein gong til
  // i pip-cachen. --target held pakkane utanfor programmappa.
  const args = [
    "-m",
    "pip",
    "install",
    "torch",
    "torchvision",
    "--index-url",
    CUDA_INDEX_URL,
    "--target",
    target,
    "--no-cache-dir",
    "--no-warn-script-location",
  ];

  send(`> python -m pip install torch torchvision (${CUDA_INDEX_URL})\n`);
  const child = spawn(python, args, { windowsHide: true });

  return new Promise((resolve) => {
    let cancelled = false;
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      if (!window.isDestroyed()) window.destroy();
      resolve(result);
    };

    const onOutput = (data) => {
      const text = data.toString();
      log?.write(text);
      send(text);
    };
    child.stdout.on("data", onOutput);
    child.stderr.on("data", onOutput);

    // Brukaren lukkar vindauget: avbryt nedlastinga.
    window.on("close", () => {
      if (settled || child.exitCode !== null) return;
      cancelled = true;
      if (IS_WINDOWS) {
        spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true });
      } else {
        child.kill("SIGKILL");
      }
    });

    child.once("error", (error) => finish({ outcome: "failed", detail: String(error.message) }));
    child.once("exit", (code) => {
      if (cancelled) return finish({ outcome: "cancelled" });
      if (code === 0 && isInstalled()) {
        updateSettings({ gpuInstalled: true });
        return finish({ outcome: "installed" });
      }
      finish({ outcome: "failed", detail: `pip avslutta med kode ${code}.` });
    });
  });
}

module.exports = {
  CUDA_INDEX_URL,
  hasNvidiaGpu,
  install,
  isInstalled,
  readSettings,
  updateSettings,
};
