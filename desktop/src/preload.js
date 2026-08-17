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

  /**
   * Opnar ei mappe eller ei fil i Utforskar eller i standardprogrammet, slik at brukaren
   * kjem til resultatet etter ei omdøyping. Gir { ok: true } eller { error }.
   */
  openPath: (target) => ipcRenderer.invoke("open-path", { target }),

  /**
   * Framdrifta i oppgåvelinja, som ein del mellom 0 og 1. -1 fjernar henne. Lèt brukaren
   * følgje med på ei lang OCR-køyring utan å ha appen framme. `running` seier om ein jobb
   * går, og styrer at maskina ikkje sovnar midt i ei køyring som varer over natta.
   */
  setProgress: (fraction, running) => ipcRenderer.send("set-progress", { fraction, running }),

  /** Varsel når ein lang jobb er ferdig. Blir berre vist om vindauget ikkje er framme. */
  notify: (title, body) => ipcRenderer.send("notify", { title, body }),

  /**
   * Melder frå når brukaren vel Hjelp > Kva er nytt, slik at sida kan opne endringsloggen.
   * Sjølve lista bur i web-UI-et, ikkje her, for då ser nettlesarversjonen den same.
   */
  onShowChanges: (callback) => ipcRenderer.on("vis-endringar", () => callback()),
});
