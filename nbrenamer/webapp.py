# ABOUTME: Lokal FastAPI-backend for NB foto-namngivar: køyrer discover/execute som bakgrunnsjobbar med framdrift.
# ABOUTME: Serverer det enkle web-UI-et og opererer på server-side mapper (appen køyrer lokalt på arkivmaskina).
from __future__ import annotations

import base64
import contextlib
import io
import os
import string
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import core, folders, pipeline
from .core import (
    DEFAULT_ID_PATTERN,
    DEFAULT_MAX_DIM,
    DEFAULT_PREFIX,
    STATUS_OK,
    OcrConfig,
    build_engine,
    gpu_available,
    reason_for,
)
from .report import (
    folder_list_path_for,
    manual_list_path_for,
    open_report_writer,
    read_processed,
    read_rows,
    write_folder_list,
    write_manual_list,
    write_rows,
)

WEB_DIR = Path(__file__).parent / "web"
# Standard mappe for rapportfiler: <prosjektrot>\rapport. Mappa blir oppretta ved skriving.
# Desktop-appen set NBR_REPORT_DIR, fordi installasjonsmappa (t.d. Program Files) ikkje er skrivbar.
DEFAULT_REPORT_DIR = Path(os.environ.get("NBR_REPORT_DIR") or Path(__file__).resolve().parent.parent / "rapport")

app = FastAPI(title="NB foto-namngivar")


# ----------------------------------------------------------------------------
# Jobb-handtering (éin aktiv jobb om gongen)
# ----------------------------------------------------------------------------
@dataclass
class Job:
    kind: str = ""
    state: str = "idle"  # idle | running | done | cancelled | error
    total: int = 0
    processed: int = 0
    counts: dict = field(default_factory=dict)
    current: str = ""
    message: str = ""
    device: str = ""
    started: float = 0.0
    elapsed: float = 0.0
    result: dict = field(default_factory=dict)


_job = Job()
_job_lock = threading.Lock()
_cancel = threading.Event()
_thread: Optional[threading.Thread] = None


def _job_snapshot() -> dict:
    with _job_lock:
        j = _job
        elapsed = (time.perf_counter() - j.started) if j.state == "running" else j.elapsed
        return {
            "kind": j.kind,
            "state": j.state,
            "total": j.total,
            "processed": j.processed,
            "counts": dict(j.counts),
            "current": j.current,
            "message": j.message,
            "device": j.device,
            "elapsed": round(elapsed, 1),
            "result": dict(j.result),
        }


def _busy() -> bool:
    with _job_lock:
        return _job.state == "running"


# ----------------------------------------------------------------------------
# Førespurnads-modellar
# ----------------------------------------------------------------------------
class DiscoverReq(BaseModel):
    input_dir: str
    report: str = "report.csv"
    tiff_dir: Optional[str] = None
    device: str = "gpu"
    gpu_id: int = 0
    max_dim: int = DEFAULT_MAX_DIM
    rotations: str = "0,90,270"
    autocontrast: bool = True
    id_pattern: str = DEFAULT_ID_PATTERN
    prefix: str = DEFAULT_PREFIX
    resume: bool = False


class ExecuteReq(BaseModel):
    report: str = "report.csv"
    output_dir: str
    move: bool = False
    overwrite: bool = False
    organize_by_year: bool = True


class SaveRow(BaseModel):
    original_jpg: str
    foto_id: Optional[str] = None
    new_basename: Optional[str] = None
    status: Optional[str] = None


class SaveReq(BaseModel):
    report: str
    rows: list[SaveRow]


# ----------------------------------------------------------------------------
# Discover-jobb
# ----------------------------------------------------------------------------
def _run_discover(req: DiscoverReq):
    report = Path(req.report)
    input_dir = Path(req.input_dir)
    tiff_dir = Path(req.tiff_dir) if req.tiff_dir else None
    try:
        processed = frozenset(read_processed(report)) if req.resume else frozenset()
        # Katalog-gjennomgangen blir gjord to gonger: fyrst for å vite kor mange filer det er,
        # så for å arbeide. Framdrifta må ha eit totaltal for å kunne vise tid som står att,
        # og ein gjennomgang utan å opne filer kostar sekund mot timar for sjølve lesinga.
        n_jpg, n_orphan, n_todo = folders.count_work(input_dir, tiff_dir, done=processed)

        with _job_lock:
            _job.total = n_todo
            _job.message = f"{n_jpg} jpg totalt, {n_todo} att å gjere"

        if not n_todo:
            _finish_job("done", "Ingenting å gjere")
            return

        engine, actual = build_engine(req.device, req.gpu_id)
        with _job_lock:
            _job.device = actual

        cfg = OcrConfig.make(req.id_pattern, req.max_dim, req.rotations, req.autocontrast, req.prefix)
        f, writer = open_report_writer(report, req.resume)
        manual_rows: list[dict] = []
        done = 0

        def on_row(row: dict):
            nonlocal done
            writer.writerow(row)
            f.flush()
            if row["status"] != STATUS_OK:
                manual_rows.append(
                    {
                        "original_jpg": row["original_jpg"],
                        "matched_tiff": row["matched_tiff"],
                        "status": row["status"],
                        "grunngjeving": reason_for(row["status"], row["error"]),
                    }
                )
            done += 1
            with _job_lock:
                _job.processed = done
                _job.current = Path(row["original_jpg"]).name
                _job.counts[row["status"]] = _job.counts.get(row["status"], 0) + 1

        try:
            folder_rows = pipeline.run_discover(
                input_dir, tiff_dir, cfg, on_row,
                engine=engine, done=processed, should_stop=_cancel.is_set,
            )
        finally:
            f.close()

        manual_list = manual_list_path_for(report)
        write_manual_list(manual_list, manual_rows)
        folder_list = folder_list_path_for(report)
        write_folder_list(folder_list, folder_rows)
        unbalanced = sum(1 for r in folder_rows if r["gjer_opp"] == "nei")

        state = "cancelled" if _cancel.is_set() else "done"
        _finish_job(
            state,
            f"Rapport: {report}",
            result={
                "report": str(report),
                "manual_list": str(manual_list),
                "manual": len(manual_rows),
                "folder_list": str(folder_list),
                "folders": len(folder_rows),
                "folders_unbalanced": unbalanced,
                "orphan_tiffs": n_orphan,
            },
        )
    except Exception as e:  # noqa: BLE001
        _finish_job("error", f"{type(e).__name__}: {e}")


def _finish_job(state: str, message: str, result: Optional[dict] = None):
    with _job_lock:
        _job.state = state
        _job.message = message
        _job.elapsed = time.perf_counter() - _job.started
        if result:
            _job.result = result


def _run_execute(req: ExecuteReq):
    try:
        rows = read_rows(Path(req.report))
        with _job_lock:
            _job.total = len(rows)
            _job.message = "Sjekkar at det er plass nok ..."

        # Ei flytting krev skriveløyve der originalane ligg. Uttrekk frå NB kjem ofte på
        # skriveverna område, og då skal me seie det éin gong i staden for å feile per fil.
        if req.move:
            locked = pipeline.unwritable_source(rows)
            if locked:
                _finish_job(
                    "error",
                    f"Kan ikkje flytte originalane: {locked} er skriveverna. Vel kopiering, "
                    "eller køyr mot ein kopi du har skriveløyve til.",
                )
                return

        # Ei flytting innanfor same volum er berre ei namneendring, og treng ikkje ledig plass.
        # Går ho på tvers av volum, blir filene kopierte og så sletta, og då gjeld kravet fullt ut.
        if not req.move or pipeline.crosses_volume(rows, Path(req.output_dir)):
            shortfall = pipeline.missing_space(rows, Path(req.output_dir))
            if shortfall:
                needed, free = shortfall
                _finish_job(
                    "error",
                    f"Ikkje nok plass i {req.output_dir}. Kopien treng {pipeline.human_bytes(needed)}, "
                    f"men berre {pipeline.human_bytes(free)} er ledig. Frigjer plass eller vel ei anna mappe.",
                )
                return

        def on_progress(idx, total, row):
            with _job_lock:
                _job.processed = idx
                _job.current = Path(row.get("original_jpg", "")).name

        stats = pipeline.execute_rows(
            rows,
            Path(req.output_dir),
            move=req.move,
            overwrite=req.overwrite,
            organize_by_year=req.organize_by_year,
            on_progress=on_progress,
            should_stop=_cancel.is_set,
        )
        state = "cancelled" if _cancel.is_set() else "done"
        _finish_job(state, f"Utdata i {req.output_dir}", result=stats)
    except Exception as e:  # noqa: BLE001
        _finish_job("error", f"{type(e).__name__}: {e}")


def _start_job(kind: str, target, arg):
    global _thread
    if _busy():
        raise HTTPException(status_code=409, detail="Ein jobb køyrer alt")
    _cancel.clear()
    with _job_lock:
        globals()["_job"] = Job(kind=kind, state="running", started=time.perf_counter())
    _thread = threading.Thread(target=target, args=(arg,), daemon=True)
    _thread.start()


# ----------------------------------------------------------------------------
# API
# ----------------------------------------------------------------------------
@app.get("/api/status")
def api_status():
    gpu = gpu_available()
    name = ""
    if gpu:
        try:
            import torch

            name = torch.cuda.get_device_name(0)
        except Exception:
            pass
    return {
        "gpu_available": gpu,
        "gpu_name": name,
        "report_dir": str(DEFAULT_REPORT_DIR),
        "foto_id_pattern": core.FOTO_ID_PATTERN,
        "foto_id_example": core.FOTO_ID_EXAMPLE,
    }


@app.post("/api/discover/start")
def api_discover_start(req: DiscoverReq):
    if not Path(req.input_dir).is_dir():
        raise HTTPException(status_code=400, detail=f"Inn-mappa finst ikkje: {req.input_dir}")
    _start_job("discover", _run_discover, req)
    return {"ok": True}


@app.post("/api/execute/start")
def api_execute_start(req: ExecuteReq):
    if not Path(req.report).is_file():
        raise HTTPException(status_code=400, detail=f"Rapporten finst ikkje: {req.report}")
    _start_job("execute", _run_execute, req)
    return {"ok": True}


@app.post("/api/cancel")
def api_cancel():
    _cancel.set()
    return {"ok": True}


@app.get("/api/job")
def api_job():
    return _job_snapshot()


def _duplicate_ids(rows: list[dict]) -> list[str]:
    """
    Foto-ID-ar som er brukte på meir enn éi rad. Slike kolliderer i steg 3, der den eine fila
    anten overskriv den andre eller blir talt som konflikt. Betre å seie frå under gjennomgangen,
    før noko er skrive til disk.
    """
    seen: dict[str, int] = {}
    for r in rows:
        fid = (r.get("foto_id") or "").strip()
        if fid:
            seen[fid] = seen.get(fid, 0) + 1
    return sorted(fid for fid, n in seen.items() if n > 1)


@app.get("/api/report")
def api_report(
    path: str,
    status: Optional[str] = None,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    p = Path(path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Rapporten finst ikkje")
    rows = read_rows(p)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    # Duplikat blir rekna over heile rapporten, ikkje berre sida som blir vist, sidan den andre
    # raden med same ID like gjerne kan liggje på ei anna side.
    duplicates = _duplicate_ids(rows)
    if status:
        # Fleire statusar kan sendast kommaseparert, slik at UI-et kan tilby «treng handarbeid»
        # som eitt val i staden for at brukaren må gå gjennom kvar statuskode for seg.
        wanted = {s.strip() for s in status.split(",") if s.strip()}
        rows = [r for r in rows if r["status"] in wanted]
    total = len(rows)
    page = rows[offset : offset + limit]
    # Grunngjevinga blir lagd på her i staden for i CSV-en, slik at ordlyden kan rettast utan
    # at gamle rapportar må skrivast om. Ved tekniske feil tek reason_for med systemfeilen.
    for row in page:
        row["grunngjeving"] = core.reason_for(row["status"], row.get("error", ""))
    return {
        "total": total,
        "counts": counts,
        "duplicates": duplicates,
        "offset": offset,
        "limit": limit,
        "rows": page,
    }


@app.get("/api/report/summary")
def api_report_summary(path: str, output_dir: Optional[str] = None):
    """
    Kva ei omdøyping av denne rapporten vil gjere. Blir vist til stadfesting før steg 3, der
    éin knapp elles ville skrive tusenvis av filer utan at brukaren såg omfanget fyrst. Med
    `output_dir` seier svaret òg kor mange byte det gjeld, og om ei flytting ville gått
    innanfor same volum. Eit foto er eit par på rundt 630 MB, så den skilnaden avgjer om
    steg 3 tek sekund eller timar.
    """
    p = Path(path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Rapporten finst ikkje")
    rows = read_rows(p)
    renamed = sum(1 for r in rows if pipeline.will_be_renamed(r))
    size, missing = pipeline.source_stats(rows)
    out = {
        "total": len(rows),
        "renamed": renamed,
        "manual": len(rows) - renamed,
        "duplicates": _duplicate_ids(rows),
        "bytes": size,
        "missing_sources": missing,
    }
    if output_dir:
        out["same_volume"] = not pipeline.crosses_volume(rows, Path(output_dir))
        out["free"] = pipeline.free_space(Path(output_dir))
    return out


@app.get("/api/statuses")
def api_statuses():
    """Kodane, dei korte namna og forklaringane, så UI-et ikkje duplisera ordlyden."""
    return [
        {"code": code, "label": label, "reason": core.REASONS.get(code, "")}
        for code, label in core.STATUS_LABELS.items()
    ]


@app.post("/api/report/save")
def api_report_save(req: SaveReq):
    p = Path(req.report)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Rapporten finst ikkje")
    # Lesejobben skriv rader til den same fila etter kvart. Skreiv me over henne samstundes,
    # ville dei to skrivingane trakka på kvarandre og rapporten blitt øydelagd.
    if _busy():
        raise HTTPException(
            status_code=409,
            detail="Ein jobb køyrer og skriv til rapporten. Vent til han er ferdig før du lagrar.",
        )
    rows = read_rows(p)
    edits = {e.original_jpg: e for e in req.rows}
    for r in rows:
        e = edits.get(r["original_jpg"])
        if not e:
            continue
        if e.status is not None:
            r["status"] = e.status
        if e.foto_id is not None:
            r["foto_id"] = e.foto_id
        if e.new_basename is not None:
            r["new_basename"] = e.new_basename
        elif e.foto_id is not None:
            r["new_basename"] = e.foto_id
    write_rows(p, rows)
    # Duplikatlista blir rekna på nytt her, slik at varselet i UI-et speglar fila som no ligg
    # på disk i staden for tilstanden før lagringa.
    return {"ok": True, "updated": len(edits), "duplicates": _duplicate_ids(rows)}


def _list_drives() -> list[dict]:
    # Tilgjengelege diskar på Windows (C:\, D:\ ...). Tom liste på andre OS.
    drives: list[dict] = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if os.path.exists(root):
            drives.append({"name": root, "path": root})
    return drives


def _ps_quote(value: str) -> str:
    # Trygt PowerShell single-quoted literal: doble enkle hermeteikn.
    return "'" + value.replace("'", "''") + "'"


# C#-interop for den moderne Windows-mappeveljaren (IFileOpenDialog med FOS_PICKFOLDERS).
# Gjev same Utforskar-dialog som fil-opne/lagre, i staden for den gamle tre-dialogen i .NET Framework.
_CSHARP_FOLDER_PICKER = r"""
using System;
using System.Runtime.InteropServices;

namespace NativeFolder {
    [ComImport, ClassInterface(ClassInterfaceType.None), Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")]
    internal class FileOpenDialogRCW { }

    [ComImport, Guid("42f85136-db7e-439c-85f1-e4075d135fc8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IFileOpenDialog {
        [PreserveSig] int Show(IntPtr parent);
        void SetFileTypes();
        void SetFileTypeIndex();
        void GetFileTypeIndex();
        void Advise();
        void Unadvise();
        void SetOptions(uint fos);
        void GetOptions(out uint pfos);
        void SetDefaultFolder(IShellItem psi);
        void SetFolder(IShellItem psi);
        void GetFolder(out IShellItem ppsi);
        void GetCurrentSelection(out IShellItem ppsi);
        void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string pszName);
        void GetFileName();
        void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string pszTitle);
        void SetOkButtonLabel();
        void SetFileNameLabel();
        void GetResult(out IShellItem ppsi);
        void AddPlace();
        void SetDefaultExtension();
        void Close();
        void SetClientGuid();
        void ClearClientData();
        void SetFilter();
        void GetResults();
        void GetSelectedItems();
    }

    [ComImport, Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IShellItem {
        void BindToHandler();
        void GetParent();
        void GetDisplayName(uint sigdnName, [MarshalAs(UnmanagedType.LPWStr)] out string ppszName);
        void GetAttributes();
        void Compare();
    }

    public static class Picker {
        const uint FOS_PICKFOLDERS = 0x00000020;
        const uint FOS_FORCEFILESYSTEM = 0x00000040;
        const uint SIGDN_FILESYSPATH = 0x80058000;

        [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
        static extern int SHCreateItemFromParsingName(string pszPath, IntPtr pbc, ref Guid riid, [MarshalAs(UnmanagedType.Interface)] out IShellItem ppv);

        [DllImport("user32.dll")]
        public static extern IntPtr GetForegroundWindow();

        public static string PickFolder(string initialDir, IntPtr owner) {
            IFileOpenDialog dlg = (IFileOpenDialog)(new FileOpenDialogRCW());
            uint opts;
            dlg.GetOptions(out opts);
            dlg.SetOptions(opts | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM);
            if (!string.IsNullOrEmpty(initialDir)) {
                try {
                    Guid iid = new Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe");
                    IShellItem item;
                    if (SHCreateItemFromParsingName(initialDir, IntPtr.Zero, ref iid, out item) == 0 && item != null) {
                        dlg.SetFolder(item);
                    }
                } catch { }
            }
            int hr = dlg.Show(owner);
            if (hr != 0) return null;
            IShellItem result;
            dlg.GetResult(out result);
            string path;
            result.GetDisplayName(SIGDN_FILESYSPATH, out path);
            return path;
        }
    }
}
"""


# Cachar den kompilerte mappeveljaren som DLL, så berre første kall betalar Roslyn-kompileringa.
_FOLDER_PICKER_DLL = str(Path(tempfile.gettempdir()) / "nbrenamer_folderpicker.dll")

# Berre éin native dialog om gongen. Hindrar at gjentekne klikk stablar opp fleire dialogar.
_pick_lock = threading.Lock()


def _native_dialog(mode: str, initial_dir: str, initial_file: str) -> Optional[str]:
    # Opnar den ekte Windows-dialogen via ein kortvarig PowerShell-prosess.
    # Returnerer vald sti, eller None om brukaren avbraut. Berre Windows.
    if mode == "folder":
        script = (
            f"$dll = {_ps_quote(_FOLDER_PICKER_DLL)}\n"
            "if (Test-Path $dll) {\n"
            "  try { Add-Type -Path $dll -ErrorAction Stop | Out-Null } catch { }\n"
            "} else {\n"
            '  $src = @"\n'
            + _CSHARP_FOLDER_PICKER
            + '\n"@\n'
            + "  Add-Type -TypeDefinition $src -Language CSharp -OutputAssembly $dll -ErrorAction Stop | Out-Null\n"
            + "  try { Add-Type -Path $dll -ErrorAction Stop | Out-Null } catch { }\n"
            + "}\n"
            + f"$dir = {_ps_quote(initial_dir)}\n"
            + "$owner = [NativeFolder.Picker]::GetForegroundWindow()\n"
            + "$p = [NativeFolder.Picker]::PickFolder($dir, $owner)\n"
            + "if ($p) { [Console]::Out.Write($p) }\n"
        )
    else:  # 'open' eller 'save': WinForms-dialogane er allereie den moderne Utforskar-varianten.
        csv_filter = "CSV-filer (*.csv)|*.csv|Alle filer (*.*)|*.*"
        cls = "OpenFileDialog" if mode == "open" else "SaveFileDialog"
        extra = "$dlg.CheckFileExists = $true\n" if mode == "open" else "$dlg.OverwritePrompt = $false\n"
        script = (
            "Add-Type -AssemblyName System.Windows.Forms | Out-Null\n"
            "$owner = New-Object System.Windows.Forms.Form\n"
            "$owner.TopMost = $true; $owner.ShowInTaskbar = $false; $owner.Opacity = 0\n"
            "$owner.Show() | Out-Null\n"
            f"$dlg = New-Object System.Windows.Forms.{cls}\n"
            f"$dlg.Filter = {_ps_quote(csv_filter)}\n"
            f"{extra}"
            f"$dir = {_ps_quote(initial_dir)}\n"
            "if ($dir -and (Test-Path $dir)) { $dlg.InitialDirectory = $dir }\n"
            f"$dlg.FileName = {_ps_quote(initial_file)}\n"
            "if ($dlg.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) "
            "{ [Console]::Out.Write($dlg.FileName) }\n"
            "$owner.Dispose()\n"
        )
    # Tving UTF-8 på stdout så æøå i stiar ikkje blir mangla via OEM-/ANSI-kodesider.
    script = "try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }\n" + script
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Sta", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    out = (proc.stdout or "").strip()
    return out or None


@app.get("/api/pick")
def api_pick(mode: str = "folder", initial: str = ""):
    if os.name != "nt":
        raise HTTPException(status_code=501, detail="Innebygd Windows-veljar er berre tilgjengeleg på Windows")
    if mode not in ("folder", "open", "save"):
        raise HTTPException(status_code=400, detail=f"Ukjent modus: {mode}")

    initial_dir, initial_file = "", ""
    if initial:
        p = Path(initial)
        if p.is_dir():
            initial_dir = str(p)
        else:
            parent = str(p.parent)
            initial_dir = parent if parent not in (".", "") else ""
            initial_file = p.name
    if mode == "save" and not initial_file:
        initial_file = "report.csv"

    if not _pick_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ein veljar er allereie open")
    try:
        path = _native_dialog(mode, initial_dir, initial_file)
    except FileNotFoundError as e:
        raise HTTPException(status_code=501, detail="PowerShell ikkje funnen") from e
    except subprocess.TimeoutExpired as e:
        raise HTTPException(status_code=504, detail="Dialogen vart ikkje lukka i tide") from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Klarte ikkje opne dialogen: {e}") from e
    finally:
        _pick_lock.release()

    if not path:
        return {"cancelled": True}
    return {"path": path}


@app.get("/api/browse")
def api_browse(path: Optional[str] = None):
    # Mappeveljar for UI-et: listar undermapper på arkivmaskina. Appen køyrer lokalt,
    # så dette er filsystemet til brukaren sin eigen maskin.
    drives = _list_drives()

    # Tom sti: vis diskane (Windows) eller filsystem-rota (andre OS).
    if not path:
        if drives:
            return {"path": "", "parent": "", "is_root": True, "drives": drives, "dirs": []}
        path = "/"

    p = Path(path)
    if not p.is_dir():
        raise HTTPException(status_code=404, detail=f"Mappa finst ikkje: {path}")
    p = p.resolve()

    dirs: list[dict] = []
    try:
        for child in sorted(p.iterdir(), key=lambda c: c.name.lower()):
            try:
                if child.is_dir():
                    dirs.append({"name": child.name, "path": str(child)})
            except (PermissionError, OSError):
                continue
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Ingen tilgang til mappa: {path}")

    # Ved disk-/filsystem-rot er parent lik mappa sjølv; då går "opp" til disk-lista.
    parent = "" if p.parent == p else str(p.parent)
    return {"path": str(p), "parent": parent, "is_root": False, "drives": drives, "dirs": dirs}


# Ein ukomprimert arkiv-TIFF på 114 megapiksel toppar på nær 600 MB medan han blir dekoda, og
# JPEG-snarvegen i load_base_image (draft) finst ikkje for TIFF. Rader for TIFF-ar utan JPEG
# gjer at tabellen kan be om fleire slike samstundes, og då må dei stå i kø: to på ein gong er
# ein minnetopp me toler, ti er det ikkje.
_big_decode = threading.Semaphore(2)


@app.get("/api/thumb")
def api_thumb(path: str, max_dim: int = 1000, rotate: int = 0):
    """
    Biletet skalert til visning. `rotate` er same vinkel som `rotation` i rapporten, altså den
    som gjorde ID-en leseleg for OCR-en. Gjennomgangen sender han med, slik at ei loddrett
    tekststripe står rett veg på skjermen i staden for at brukaren må tyde biletet på sida.
    """
    p = Path(path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Fila finst ikkje")
    queue = _big_decode if p.suffix.lower() in core.TIFF_SUFFIXES else contextlib.nullcontext()
    try:
        with queue:
            img = core.load_base_image(p, max_dim, autocontrast=False)
            if rotate % 360:
                img = img.rotate(rotate, expand=True)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
        buf.seek(0)
        return StreamingResponse(buf, media_type="image/jpeg")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="static")
