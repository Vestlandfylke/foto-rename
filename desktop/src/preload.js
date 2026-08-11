// ABOUTME: Bru mellom web-UI-et og Electron, slik at «Bla gjennom ...» kan bruke systemdialogen.
// ABOUTME: Eksponerer berre éi funksjon; all validering av argumenta skjer i hovudprosessen.
"use strict";

const { contextBridge, ipcRenderer } = require("electron");

// contextIsolation er på, så sida ser berre det som blir lagt ut her, korkje Node eller ipcRenderer.
// UI-et sjekkar om `window.nbrDesktop` finst: i nettlesaren gjer han ikkje det, og då fell
// «Bla gjennom ...» tilbake til veljaren i backenden.
contextBridge.exposeInMainWorld("nbrDesktop", {
  /**
   * Opnar den ekte systemdialogen. `mode` er "folder", "open" eller "save", og `initial`
   * er stien feltet har i dag. Gir { path } eller { cancelled: true }.
   */
  pickPath: (mode, initial) => ipcRenderer.invoke("pick-path", { mode, initial }),
});
