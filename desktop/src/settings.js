// ABOUTME: Les og skriv settings.json i userData, den vesle tilstanden appen hugsar mellom køyringar.
// ABOUTME: Tilstanden bur her og ikkje i sida, fordi backenden får ny port kvar oppstart og localStorage følgjer porten.
"use strict";

const { app } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

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

module.exports = { settingsPath, readSettings, updateSettings };
