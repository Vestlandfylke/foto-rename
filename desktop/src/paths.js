// ABOUTME: Delte stiar for desktop-appen: Python-tolken, backend-mappa og mappa for GPU-pakkar.
// ABOUTME: Skil mellom utviklingsmodus (.venv i prosjektrota) og pakka app (resources\runtime).
"use strict";

const { app } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

// Prosjektrota i utviklingsmodus: desktop\src -> desktop -> foto-rename.
const PROJECT_ROOT = path.resolve(__dirname, "..", "..");

/** Mappa som inneheld `nbrenamer`-pakken. */
function backendRoot() {
  return app.isPackaged ? path.join(process.resourcesPath, "backend") : PROJECT_ROOT;
}

/**
 * Python-tolken som køyrer backenden. Pakka app brukar den innebygde runtime-en;
 * i utvikling brukar me .venv i prosjektrota, same miljø som start-app.ps1.
 */
function resolvePython() {
  const candidates = app.isPackaged
    ? [path.join(process.resourcesPath, "runtime", "python.exe")]
    : [
        path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe"),
        path.join(PROJECT_ROOT, ".venv", "bin", "python"),
      ];
  return candidates.find((candidate) => fs.existsSync(candidate)) ?? null;
}

/**
 * Mappa der GPU-pakkane (torch med CUDA) blir installerte etterpå, på etterspurnad.
 * Dei ligg utanfor programmappa av to grunnar: programmappa kan vere skriveverna
 * (t.d. ved installasjon i Program Files), og dei fleire GB-ane skal ikkje hamne i
 * ein roaming-profil som blir synkronisert.
 */
function gpuSiteDir() {
  const base =
    process.platform === "win32" && process.env.LOCALAPPDATA
      ? path.join(process.env.LOCALAPPDATA, "NB foto-namngivar")
      : app.getPath("userData");
  return path.join(base, "gpu-packages");
}

module.exports = { PROJECT_ROOT, backendRoot, resolvePython, gpuSiteDir };
