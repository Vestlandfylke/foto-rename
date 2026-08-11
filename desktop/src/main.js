// ABOUTME: Electron-hovudprosess for NB foto-namngivar: startar den lokale Python-backenden og viser UI-et i eit appvindauge.
// ABOUTME: Backenden bind seg til 127.0.0.1 på ein ledig port, og blir alltid avslutta saman med appen.
"use strict";

const { app, BrowserWindow, Menu, Notification, dialog, ipcMain, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");

const gpu = require("./gpu");
const updater = require("./updater");
const { APP_ICON, PROJECT_ROOT, backendRoot, gpuSiteDir, resolvePython } = require("./paths");

const IS_WINDOWS = process.platform === "win32";
const STARTUP_TIMEOUT_MS = 120_000;

let backend = null;
let backendLog = null;
let logPath = "";
let mainWindow = null;
let splashWindow = null;
let backendUrl = "";
let shuttingDown = false;

function openLog() {
  const dir = app.getPath("logs");
  fs.mkdirSync(dir, { recursive: true });
  logPath = path.join(dir, "backend.log");
  backendLog = fs.createWriteStream(logPath, { flags: "a" });
  backendLog.write(`\n=== ${new Date().toISOString()} start (packaged=${app.isPackaged}) ===\n`);
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.unref();
    probe.once("error", reject);
    probe.listen(0, "127.0.0.1", () => {
      const { port } = probe.address();
      probe.close(() => resolve(port));
    });
  });
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Sjekkar om noko svarar på porten. Me ventar på TCP, ikkje på /api/status, som lastar torch. */
function portIsOpen(port) {
  return new Promise((resolve) => {
    const socket = net.connect({ host: "127.0.0.1", port });
    const done = (result) => {
      socket.destroy();
      resolve(result);
    };
    socket.setTimeout(1000);
    socket.once("connect", () => done(true));
    socket.once("timeout", () => done(false));
    socket.once("error", () => done(false));
  });
}

/** Hentar /api/status frå backenden. Returnerer null om kallet ikkje går gjennom. */
function fetchStatus() {
  return new Promise((resolve) => {
    const request = http.get(`${backendUrl}api/status`, { timeout: 30_000 }, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => (body += chunk));
      response.on("end", () => {
        try {
          resolve(JSON.parse(body));
        } catch {
          resolve(null);
        }
      });
    });
    request.once("error", () => resolve(null));
    request.once("timeout", () => {
      request.destroy();
      resolve(null);
    });
  });
}

/**
 * Køyrer GPU-installasjonen og ber om omstart etterpå. torch lastar CUDA-bibliotek når
 * det blir importert fyrste gong, så ein fersk backend-prosess er den trygge vegen.
 */
async function runGpuInstall() {
  const result = await gpu.install(mainWindow, backendLog);

  if (result.outcome === "cancelled") return;

  if (result.outcome === "failed") {
    dialog.showMessageBox(mainWindow, {
      type: "error",
      title: "GPU-installasjonen feila",
      message: "Klarte ikkje installere GPU-akselerasjon.",
      detail: `${result.detail ?? ""}\n\nAppen held fram på CPU. Detaljar i loggen:\n${logPath}`.trim(),
    });
    return;
  }

  const { response } = await dialog.showMessageBox(mainWindow, {
    type: "info",
    title: "GPU-akselerasjon er klar",
    message: "GPU-akselerasjon er installert.",
    detail: "Appen må startast på nytt for å ta det i bruk.",
    buttons: ["Start på nytt no", "Seinare"],
    defaultId: 0,
    cancelId: 1,
  });
  if (response === 0) {
    app.relaunch();
    app.quit();
  }
}

/**
 * Menyvalet for GPU: fortel kva tilstand maskina er i, og tilbyr installasjon berre når
 * det faktisk er noko å installere. Backenden er sanninga om GPU er i bruk, ikkje om
 * pakkane finst, sidan torch like godt kan vere installert i eit .venv i utvikling.
 */
async function showGpuDialog() {
  const status = await fetchStatus();

  if (status?.gpu_available) {
    dialog.showMessageBox(mainWindow, {
      type: "info",
      title: "GPU-akselerasjon",
      message: `GPU-akselerasjon er i bruk${status.gpu_name ? `: ${status.gpu_name}` : ""}.`,
      detail: "OCR-lesinga køyrer på grafikkortet.",
    });
    return;
  }

  if (gpu.isInstalled()) {
    dialog.showMessageBox(mainWindow, {
      type: "warning",
      title: "GPU-akselerasjon",
      message: "GPU-pakkane er installerte, men blir ikkje brukte.",
      detail: `Prøv å starte appen på nytt. Held det fram, sjekk at grafikkortdrivaren er oppdatert.\n\nDetaljar i loggen:\n${logPath}`,
    });
    return;
  }

  if (!(await hasNvidiaGpuOrLog())) {
    dialog.showMessageBox(mainWindow, {
      type: "info",
      title: "GPU-akselerasjon",
      message: "Fann ikkje noko NVIDIA-grafikkort på denne maskina.",
      detail: "OCR-lesinga køyrer på CPU. Det verkar, men er tregare.",
    });
    return;
  }

  const { response } = await dialog.showMessageBox(mainWindow, {
    type: "question",
    title: "GPU-akselerasjon",
    message: "Vil du installere GPU-akselerasjon no?",
    detail: "Nedlastinga er på 2 til 3 GB og skjer berre denne eine gongen.",
    buttons: ["Installer", "Avbryt"],
    defaultId: 0,
    cancelId: 1,
  });
  if (response === 0) await runGpuInstall();
}

/**
 * Stengjer ned backenden før eit installasjonsprogram byter ut filene. Utan dette ville
 * `before-quit` utsett avslutninga, og oppdateringa kunne starte mens Python held filer opne.
 */
async function prepareQuit() {
  shuttingDown = true;
  await stopBackend();
}

/**
 * Oppdateringssjekk fyrst, så GPU-tilbodet. Rekkjefølgja er med vilje: dei skal ikkje
 * leggje dialogar oppå kvarandre, og ei ny versjon kan vere det brukaren treng aller fyrst.
 */
async function runStartupTasks() {
  await updater.check({ parentWindow: mainWindow, silent: true, prepareQuit, log: backendLog });
  await maybeOfferGpu();
}

/** Spør éin gong om brukaren vil slå på GPU, når maskina har eit NVIDIA-kort som ikkje er i bruk. */
async function maybeOfferGpu() {
  if (gpu.isInstalled() || gpu.readSettings().gpuOfferDismissed) return;

  const status = await fetchStatus();
  if (!status || status.gpu_available) return;
  if (!(await hasNvidiaGpuOrLog())) return;

  const { response, checkboxChecked } = await dialog.showMessageBox(mainWindow, {
    type: "question",
    title: "GPU-akselerasjon",
    message: "Maskina har eit NVIDIA-grafikkort som ikkje er i bruk.",
    detail:
      "GPU gjer OCR-lesinga mykje raskare. Nedlastinga er på 2 til 3 GB og skjer berre denne eine gongen.\n\nDu kan alltid gjere dette seinare frå menyen Verktøy.",
    buttons: ["Installer no", "Ikkje no"],
    checkboxLabel: "Ikkje spør meg igjen",
    defaultId: 0,
    cancelId: 1,
  });

  if (checkboxChecked) gpu.updateSettings({ gpuOfferDismissed: true });
  if (response === 0) await runGpuInstall();
}

async function hasNvidiaGpuOrLog() {
  const found = await gpu.hasNvidiaGpu();
  backendLog?.write(`=== nvidia-smi funne: ${found} ===\n`);
  return found;
}

function startBackend(port) {
  const python = resolvePython();
  if (!python) {
    throw new Error(
      app.isPackaged
        ? "Fann ikkje det innebygde Python-miljøet. Installasjonen ser skadd ut, prøv å installere appen på nytt."
        : `Fann ikkje .venv i ${PROJECT_ROOT}. Køyr Installer.bat (eller .\\setup.ps1) fyrst.`
    );
  }

  const env = {
    ...process.env,
    PYTHONUTF8: "1",
    PYTHONUNBUFFERED: "1",
    // GPU-pakkane blir installerte på etterspurnad, utanfor programmappa.
    NBR_EXTRA_SITE: gpuSiteDir(),
  };
  if (app.isPackaged) {
    // Programmappa kan vere skriveverna, så rapportane hamnar i Dokument.
    env.NBR_REPORT_DIR = path.join(app.getPath("documents"), "NB foto-namngivar", "rapport");
  }

  const child = spawn(
    python,
    ["-m", "nbrenamer.desktop_server", "--port", String(port), "--watch-stdin"],
    { cwd: backendRoot(), env, windowsHide: true, stdio: ["pipe", "pipe", "pipe"] }
  );

  child.stdout.pipe(backendLog, { end: false });
  child.stderr.pipe(backendLog, { end: false });
  child.once("exit", (code, signal) => {
    backendLog?.write(`=== backend avslutta (code=${code} signal=${signal}) ===\n`);
    if (child === backend) {
      backend = null;
      if (!shuttingDown) {
        fatal(
          "Backenden stoppa uventa",
          `Python-prosessen avslutta med kode ${code}.\n\nDetaljar i loggen:\n${logPath}`
        );
      }
    }
  });

  return child;
}

async function waitForBackend(port) {
  const deadline = Date.now() + STARTUP_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (!backend) throw new Error(`Backenden stoppa under oppstart. Sjå loggen:\n${logPath}`);
    if (await portIsOpen(port)) return;
    await delay(250);
  }
  throw new Error(
    `Backenden svarte ikkje innan ${STARTUP_TIMEOUT_MS / 1000} sekund. Sjå loggen:\n${logPath}`
  );
}

/**
 * Ber backenden avslutte ved å lukke stdin, og tvingar han ned om han ikkje høyrer etter.
 * taskkill /T tek med eventuelle barneprosessar (t.d. PowerShell-dialogar).
 */
function stopBackend() {
  const child = backend;
  backend = null;
  if (!child || child.exitCode !== null) return Promise.resolve();

  return new Promise((resolve) => {
    const hardKill = setTimeout(() => {
      if (IS_WINDOWS) {
        spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true });
      } else {
        child.kill("SIGKILL");
      }
      setTimeout(resolve, 1000);
    }, 4000);

    child.once("exit", () => {
      clearTimeout(hardKill);
      resolve();
    });

    try {
      child.stdin.end();
    } catch {
      /* stdin kan alt vere borte */
    }
    if (!IS_WINDOWS) child.kill("SIGTERM");
  });
}

function fatal(title, message) {
  splashWindow?.destroy();
  splashWindow = null;
  dialog.showErrorBox(title, message);
  shuttingDown = true;
  stopBackend().finally(() => app.exit(1));
}

const CSV_FILTERS = [
  { name: "CSV-filer", extensions: ["csv"] },
  { name: "Alle filer", extensions: ["*"] },
];

/**
 * Startstien dialogen skal opne på. Windows ignorerer ein sti som ikkje finst, så me sender
 * berre med det som faktisk ligg der: mappa sjølv, eller mappa til eit filnamn.
 */
function dialogDefaultPath(mode, initial) {
  if (!initial) return undefined;
  if (mode === "folder") return fs.existsSync(initial) ? initial : undefined;
  return fs.existsSync(path.dirname(initial)) ? initial : undefined;
}

/**
 * Systemdialogen bak «Bla gjennom ...» i UI-et. I nettlesaren må dette gå om backenden, som
 * startar ein eigen PowerShell-prosess per klikk og kompilerer mappeveljaren fyrste gongen.
 * Her er dialogen ein del av appen, så han opnar seg med ein gong og blir modal over
 * vindauget i staden for å kunne hamne bak det.
 */
function registerPickHandler() {
  ipcMain.handle("pick-path", async (event, { mode, initial } = {}) => {
    const parent = BrowserWindow.fromWebContents(event.sender);
    const defaultPath = dialogDefaultPath(mode, typeof initial === "string" ? initial.trim() : "");

    if (mode === "save") {
      const { canceled, filePath } = await dialog.showSaveDialog(parent, {
        title: "Lagre rapportfila",
        filters: CSV_FILTERS,
        defaultPath,
      });
      return canceled ? { cancelled: true } : { path: filePath };
    }

    const folder = mode === "folder";
    if (!folder && mode !== "open") throw new Error(`Ukjent dialogmodus: ${mode}`);
    const { canceled, filePaths } = await dialog.showOpenDialog(parent, {
      title: folder ? "Vel mappe" : "Vel rapportfil",
      properties: [folder ? "openDirectory" : "openFile"],
      filters: folder ? undefined : CSV_FILTERS,
      defaultPath,
    });
    return canceled ? { cancelled: true } : { path: filePaths[0] };
  });
}

/**
 * Opnar ut-mappa eller rapporten etter ei køyring. Ei mappe blir opna i Utforskar; ei fil blir
 * vist i mappa si i staden for å bli starta, slik at appen aldri køyrer noko for brukaren.
 */
function registerOpenHandler() {
  ipcMain.handle("open-path", async (event, { target } = {}) => {
    const wanted = typeof target === "string" ? target.trim() : "";
    if (!wanted || !fs.existsSync(wanted)) return { error: "Fann ikkje stien" };

    if (fs.statSync(wanted).isDirectory()) {
      const error = await shell.openPath(wanted);
      return error ? { error } : { ok: true };
    }
    shell.showItemInFolder(wanted);
    return { ok: true };
  });
}

/**
 * Ei OCR-køyring over eit heilt arkivuttrekk kan ta timar. Då skal brukaren kunne gjere anna
 * arbeid og likevel sjå kor langt det har komme, og bli varsla når det er gjort.
 */
function registerProgressHandlers() {
  ipcMain.on("set-progress", (event, { fraction } = {}) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    win?.setProgressBar(typeof fraction === "number" ? fraction : -1);
  });

  ipcMain.on("notify", (event, { title, body } = {}) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    // Står vindauget framme, ser brukaren alt resultatet, og eit varsel er berre støy.
    if (!win || win.isFocused()) return;

    win.flashFrame(true);
    if (!Notification.isSupported()) return;
    const varsel = new Notification({
      title: String(title || ""),
      body: String(body || ""),
      icon: APP_ICON,
    });
    varsel.on("click", () => {
      if (win.isMinimized()) win.restore();
      win.focus();
    });
    varsel.show();
  });
}

function createSplash() {
  splashWindow = new BrowserWindow({
    width: 460,
    height: 260,
    frame: false,
    resizable: false,
    center: true,
    show: true,
    backgroundColor: "#0A3258",
    icon: APP_ICON,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  splashWindow.loadFile(path.join(__dirname, "splash.html"));
  splashWindow.once("closed", () => {
    splashWindow = null;
  });
}

function createMainWindow(url) {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 880,
    minWidth: 1000,
    minHeight: 700,
    show: false,
    backgroundColor: "#eef2f7",
    title: "NB foto-namngivar",
    icon: APP_ICON,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      spellcheck: false,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  // Blinkinga frå eit ferdigvarsel har gjort jobben sin når brukaren kjem tilbake.
  mainWindow.on("focus", () => mainWindow.flashFrame(false));

  // Alt utanfor den lokale backenden skal opnast i systemnettlesaren, ikkje i appvindauget.
  mainWindow.webContents.setWindowOpenHandler(({ url: target }) => {
    if (target.startsWith("http://") || target.startsWith("https://")) shell.openExternal(target);
    return { action: "deny" };
  });
  mainWindow.webContents.on("will-navigate", (event, target) => {
    if (!target.startsWith(url)) {
      event.preventDefault();
      if (target.startsWith("https://")) shell.openExternal(target);
    }
  });

  mainWindow.once("ready-to-show", () => {
    splashWindow?.destroy();
    splashWindow = null;
    mainWindow.show();
    // Etter at UI-et er synleg, så dialogane ikkje forseinkar oppstarten.
    runStartupTasks().catch((error) => backendLog?.write(`=== oppstartsjobb feila: ${error} ===\n`));
  });
  // Berre feil på sjølve hovudsida er kritiske. Ein underressurs som ikkje lastar skal ikkje
  // drepe appen, og ERR_ABORTED (-3) kjem av heilt vanlege avbrotne navigeringar.
  mainWindow.webContents.on("did-fail-load", (_event, code, description, failedUrl, isMainFrame) => {
    if (!isMainFrame || code === -3) return;
    fatal(
      "Klarte ikkje laste grensesnittet",
      `Backenden svarte ikkje på ${failedUrl} (${description}, kode ${code}).\n\nDetaljar i loggen:\n${logPath}`
    );
  });
  mainWindow.once("closed", () => {
    mainWindow = null;
  });

  mainWindow.loadURL(url);
}

function buildMenu() {
  Menu.setApplicationMenu(
    Menu.buildFromTemplate([
      {
        label: "Fil",
        submenu: [{ label: "Lukk appen", role: "quit" }],
      },
      {
        label: "Rediger",
        submenu: [
          { label: "Angre", role: "undo" },
          { label: "Gjer om", role: "redo" },
          { type: "separator" },
          { label: "Klipp ut", role: "cut" },
          { label: "Kopier", role: "copy" },
          { label: "Lim inn", role: "paste" },
          { label: "Merk alt", role: "selectAll" },
        ],
      },
      {
        label: "Vis",
        submenu: [
          { label: "Last inn på nytt", role: "reload" },
          { label: "Større tekst", role: "zoomIn" },
          { label: "Mindre tekst", role: "zoomOut" },
          { label: "Normal storleik", role: "resetZoom" },
          { type: "separator" },
          { label: "Fullskjerm", role: "togglefullscreen" },
          { label: "Utviklarverktøy", role: "toggleDevTools" },
        ],
      },
      {
        label: "Verktøy",
        submenu: [
          { label: "GPU-akselerasjon ...", click: () => showGpuDialog() },
        ],
      },
      {
        label: "Hjelp",
        submenu: [
          {
            label: "Sjekk etter oppdateringar ...",
            click: () =>
              updater.check({
                parentWindow: mainWindow,
                silent: false,
                prepareQuit,
                log: backendLog,
              }),
          },
          {
            label: "Opne loggmappa",
            click: () => shell.openPath(app.getPath("logs")),
          },
          {
            label: "Om NB foto-namngivar",
            click: () =>
              dialog.showMessageBox(mainWindow, {
                type: "info",
                title: "Om NB foto-namngivar",
                message: "NB foto-namngivar",
                detail: [
                  `Versjon ${app.getVersion()}`,
                  `Electron ${process.versions.electron}`,
                  "",
                  "Vestland fylkeskommune. All OCR skjer lokalt på denne maskina.",
                ].join("\n"),
              }),
          },
        ],
      },
    ])
  );
}

async function boot() {
  openLog();
  buildMenu();
  registerPickHandler();
  registerOpenHandler();
  registerProgressHandlers();
  createSplash();

  try {
    const port = await findFreePort();
    backend = startBackend(port);
    await waitForBackend(port);
    if (shuttingDown) return;
    backendUrl = `http://127.0.0.1:${port}/`;
    createMainWindow(backendUrl);
  } catch (error) {
    fatal("Klarte ikkje starte NB foto-namngivar", String(error.message ?? error));
  }
}

if (!app.requestSingleInstanceLock()) {
  app.exit(0);
} else {
  app.setAppUserModelId("no.vestlandfylke.nbfotonamngivar");

  app.on("second-instance", () => {
    const window = mainWindow ?? splashWindow;
    if (window) {
      if (window.isMinimized()) window.restore();
      window.focus();
    }
  });

  app.whenReady().then(boot);

  app.on("window-all-closed", () => app.quit());

  // Backenden må vere heilt nede før Electron avsluttar, elles kan porten bli ståande oppteken.
  app.on("before-quit", (event) => {
    if (shuttingDown || !backend) return;
    shuttingDown = true;
    event.preventDefault();
    stopBackend().finally(() => app.quit());
  });
}
