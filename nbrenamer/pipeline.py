# ABOUTME: Orkestrering av discover (OCR av mange filer) og execute (kopier/omdøyp) for NB foto-namngivar.
# ABOUTME: Tilbyr både sekvensiell køyring (web/GPU) og multiprosess (CPU-batch via CLI), med framdrifts-callback.
from __future__ import annotations

import shutil
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional

from . import core
from .core import OcrConfig, build_engine, process_one, reason_for, STATUS_OK
from .report import write_manual_list

# ----------------------------------------------------------------------------
# discover
# ----------------------------------------------------------------------------
_W: dict = {}


def _worker_init(pattern_str, max_dim, rotations, autocontrast, prefix, device, gpu_id):
    _W["cfg"] = OcrConfig.make(pattern_str, max_dim, rotations, autocontrast, prefix)
    engine, actual = build_engine(device, gpu_id)
    _W["engine"] = engine
    _W["device"] = actual


def _worker_process(jpg_str: str, tiff_dir_str: Optional[str]) -> dict:
    tiff_dir = Path(tiff_dir_str) if tiff_dir_str else None
    return process_one(_W["engine"], Path(jpg_str), tiff_dir, _W["cfg"])


def run_discover_sequential(
    todo: list[Path],
    engine,
    tiff_dir: Optional[Path],
    cfg: OcrConfig,
    on_row: Callable[[dict, int], None],
    should_stop: Optional[Callable[[], bool]] = None,
) -> None:
    for i, jpg in enumerate(todo, 1):
        if should_stop and should_stop():
            break
        on_row(process_one(engine, jpg, tiff_dir, cfg), i)


def run_discover_multiprocess(
    todo: list[Path],
    tiff_dir: Optional[Path],
    init_primitives: tuple,
    on_row: Callable[[dict, int], None],
    workers: int,
) -> None:
    tiff_dir_str = str(tiff_dir) if tiff_dir else None
    with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init, initargs=init_primitives) as ex:
        futures = {ex.submit(_worker_process, str(jpg), tiff_dir_str): jpg for jpg in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            on_row(fut.result(), i)


# ----------------------------------------------------------------------------
# execute
# ----------------------------------------------------------------------------
def _place_file(src: Path, dest: Path, move: bool, overwrite: bool) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not overwrite:
        return "konflikt"
    if move:
        shutil.move(str(src), str(dest))
    else:
        shutil.copy2(str(src), str(dest))
    return "ok"


def execute_rows(
    rows: list[dict],
    output_dir: Path,
    move: bool = False,
    overwrite: bool = False,
    organize_by_year: bool = False,
    on_progress: Optional[Callable[[int, int, dict], None]] = None,
) -> dict:
    """Kopierer/omdøyper etter rapport-radene. Returnerer statistikk og sti til manuell-lista."""
    output_dir = Path(output_dir)
    manual_root = output_dir / "_manuell"
    stats = {"omdøypt": 0, "manuell": 0, "konflikt": 0}
    manual_rows: list[dict] = []
    total = len(rows)

    for idx, row in enumerate(rows, 1):
        jpg = Path(row["original_jpg"])
        tiff = Path(row["matched_tiff"]) if row.get("matched_tiff") else None
        status = row["status"]

        if status == STATUS_OK and row.get("new_basename"):
            target_dir = output_dir / row["year"] if (organize_by_year and row.get("year")) else output_dir
            base = row["new_basename"]
            res = _place_file(jpg, target_dir / (base + jpg.suffix.lower()), move, overwrite)
            if res == "konflikt":
                stats["konflikt"] += 1
            else:
                if tiff and tiff.exists():
                    _place_file(tiff, target_dir / (base + tiff.suffix.lower()), move, overwrite)
                stats["omdøypt"] += 1
        else:
            sub = manual_root / status
            _place_file(jpg, sub / jpg.name, move, overwrite)
            if tiff and tiff.exists():
                _place_file(tiff, sub / tiff.name, move, overwrite)
            stats["manuell"] += 1
            manual_rows.append(
                {
                    "original_jpg": row["original_jpg"],
                    "matched_tiff": row.get("matched_tiff", ""),
                    "status": status,
                    "grunngjeving": reason_for(status, row.get("error", "")),
                    "kopiert_til": str(sub),
                }
            )

        if on_progress:
            on_progress(idx, total, row)

    manual_list = manual_root / "uidentifiserte.csv"
    if manual_rows:
        write_manual_list(manual_list, manual_rows)

    stats["manual_list"] = str(manual_list) if manual_rows else ""
    return stats
