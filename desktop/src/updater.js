// ABOUTME: Sjekkar GitHub-releases for nyare versjonar, og lastar ned og installerer på brukaren sitt samtykke.
// ABOUTME: Heilt passiv i utviklingsmodus, der det ikkje finst nokon installert app å oppdatere.
"use strict";

const { BrowserWindow, app, dialog } = require("electron");
const path = require("node:path");

const { autoUpdater } = require("electron-updater");

const { APP_ICON } = require("./paths");

let configured = false;
let busy = false;

function configure(log) {
  if (configured) return;
  configured = true;

  // Me spør brukaren før noko blir lasta ned, og styrer installasjonen sjølv, fordi
  // Python-backenden må stoppast før installasjonsprogrammet byter ut filene.
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = false;

  const write = (level, message) => log?.write(`[updater ${level}] ${message}\n`);
  autoUpdater.logger = {
    info: (m) => write("info", String(m)),
    warn: (m) => write("warn", String(m)),
    error: (m) => write("error", String(m)),
    debug: () => {},
  };
}

function createProgressWindow(parent) {
  const window = new BrowserWindow({
    width: 560,
    height: 260,
    parent: parent ?? undefined,
    show: true,
    title: "Lastar ned oppdatering",
    backgroundColor: "#0A3258",
    icon: APP_ICON,
    resizable: false,
    maximizable: false,
    minimizable: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  window.setMenuBarVisibility(false);
  window.loadFile(path.join(__dirname, "update.html"));
  return window;
}

function downloadWithProgress(parentWindow, result, log) {
  const window = createProgressWindow(parentWindow);
  let pageReady = false;
  let settled = false;
  let cancelled = false;
  let latest = null;

  const push = () => {
    if (!pageReady || latest === null || window.isDestroyed()) return;
    window.webContents
      .executeJavaScript(`window.setProgress(${JSON.stringify(latest)})`)
      .catch(() => {});
  };
  window.webContents.once("did-finish-load", () => {
    pageReady = true;
    window.webContents
      .executeJavaScript(`window.setVersion(${JSON.stringify(result.updateInfo.version)})`)
      .catch(() => {});
    push();
  });

  const onProgress = (progress) => {
    latest = {
      percent: progress.percent ?? 0,
      transferred: progress.transferred ?? 0,
      total: progress.total ?? 0,
      bytesPerSecond: progress.bytesPerSecond ?? 0,
    };
    push();
  };
  autoUpdater.on("download-progress", onProgress);

  window.on("close", () => {
    if (settled) return;
    cancelled = true;
    result.cancellationToken?.cancel();
  });

  const cleanup = () => {
    settled = true;
    autoUpdater.removeListener("download-progress", onProgress);
    if (!window.isDestroyed()) window.destroy();
  };

  return autoUpdater
    .downloadUpdate(result.cancellationToken)
    .then(() => {
      cleanup();
      return { outcome: cancelled ? "cancelled" : "downloaded" };
    })
    .catch((error) => {
      cleanup();
      log?.write(`[updater error] nedlasting feila: ${error}\n`);
      return cancelled
        ? { outcome: "cancelled" }
        : { outcome: "failed", detail: String(error?.message ?? error) };
    });
}

/**
 * Sjekkar etter ny versjon. `silent` styrer om brukaren skal få melding når det
 * ikkje er noko nytt eller når sjekken feilar, slik at oppstart ikkje blir masete
 * på ei maskin utan nettilgang.
 */
async function check({ parentWindow, silent, prepareQuit, log }) {
  configure(log);

  if (!app.isPackaged) {
    if (!silent) {
      dialog.showMessageBox(parentWindow, {
        type: "info",
        title: "Oppdateringar",
        message: "Oppdateringar gjeld berre den installerte utgåva.",
        detail: `Du køyrer appen frå kjeldekoden (versjon ${app.getVersion()}).`,
      });
    }
    return;
  }

  if (busy) {
    if (!silent) {
      dialog.showMessageBox(parentWindow, {
        type: "info",
        title: "Oppdateringar",
        message: "Ei oppdatering er alt i arbeid.",
      });
    }
    return;
  }

  busy = true;
  try {
    let result = null;
    try {
      result = await autoUpdater.checkForUpdates();
    } catch (error) {
      log?.write(`[updater error] sjekk feila: ${error}\n`);
      if (!silent) {
        dialog.showMessageBox(parentWindow, {
          type: "error",
          title: "Oppdateringar",
          message: "Klarte ikkje sjekke etter oppdateringar.",
          detail: `${String(error?.message ?? error)}\n\nSjekk at maskina har nettilgang.`,
        });
      }
      return;
    }

    if (!result?.isUpdateAvailable) {
      if (!silent) {
        dialog.showMessageBox(parentWindow, {
          type: "info",
          title: "Oppdateringar",
          message: `Du har nyaste versjon (${app.getVersion()}).`,
        });
      }
      return;
    }

    const { response } = await dialog.showMessageBox(parentWindow, {
      type: "question",
      title: "Ny versjon tilgjengeleg",
      message: `Versjon ${result.updateInfo.version} er klar.`,
      detail: `Du har versjon ${app.getVersion()}. Vil du laste ned oppdateringa no?`,
      buttons: ["Last ned", "Ikkje no"],
      defaultId: 0,
      cancelId: 1,
    });
    if (response !== 0) return;

    const download = await downloadWithProgress(parentWindow, result, log);
    if (download.outcome === "cancelled") return;
    if (download.outcome === "failed") {
      dialog.showMessageBox(parentWindow, {
        type: "error",
        title: "Oppdateringa feila",
        message: "Klarte ikkje laste ned oppdateringa.",
        detail: download.detail ?? "",
      });
      return;
    }

    const installNow = await dialog.showMessageBox(parentWindow, {
      type: "info",
      title: "Oppdateringa er klar",
      message: `Versjon ${result.updateInfo.version} er lasta ned.`,
      detail:
        "Appen blir installert og starta på nytt. Har du ein jobb som køyrer, kan du velje å vente.",
      buttons: ["Installer og start på nytt", "Installer når eg lukkar appen"],
      defaultId: 0,
      cancelId: 1,
    });

    if (installNow.response === 0) {
      // Backenden må vere heilt nede før installasjonsprogrammet byter ut filene.
      await prepareQuit?.();
      autoUpdater.quitAndInstall(false, true);
      return;
    }
    autoUpdater.autoInstallOnAppQuit = true;
  } finally {
    busy = false;
  }
}

module.exports = { check };
