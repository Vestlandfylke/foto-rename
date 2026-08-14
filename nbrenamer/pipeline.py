# ABOUTME: Orkestrering av discover (OCR av mange filer) og execute (kopier/omdøyp) for NB foto-namngivar.
# ABOUTME: Tilbyr både sekvensiell køyring (web/GPU) og multiprosess (CPU-batch via CLI), med framdrifts-callback.
from __future__ import annotations

import os
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


def source_paths(rows: list[dict]) -> list[Path]:
    """Alle filene radene peikar på, både JPEG og TIFF."""
    out: list[Path] = []
    for row in rows:
        for key in ("original_jpg", "matched_tiff"):
            value = row.get(key)
            if value:
                out.append(Path(value))
    return out


def source_stats(rows: list[dict]) -> tuple[int, int]:
    """
    (byte, filer som ikkje finst) for alt radene peikar på. Byte-talet er kor mykje plass
    køyringa legg beslag på i ut-mappa; eit skann er eit par på rundt 630 MB, så talet blir fort
    terabyte, og brukaren bør sjå det før han startar. Filer som ikkje finst tel som null byte og
    blir rapporterte som feil under sjølve køyringa, men talet på dei er verdt å vise på førehand:
    ein rapport som peikar på ein nettverksdisk som ikkje er kopla til, ser elles ut som ei
    køyring utan data.
    """
    total = 0
    missing = 0
    for path in source_paths(rows):
        try:
            total += path.stat().st_size
        except OSError:
            missing += 1
    return total, missing


def total_bytes(rows: list[dict]) -> int:
    """Kor mykje data køyringa flyttar på."""
    return source_stats(rows)[0]


def _volume_of(path: Path) -> str:
    """Volumet stien ligg på, altså `d:` eller `\\\\tenar\\utdeling`. Tom streng for relative stiar."""
    return os.path.splitdrive(os.path.abspath(str(path)))[0].lower()


def crosses_volume(rows: list[dict], output_dir: Path) -> bool:
    """
    Sant når minst éi kjeldefil ligg på eit anna volum enn ut-mappa. Ei flytting innanfor same
    volum er berre ei namneendring i filsystemet: momentan, og utan behov for ledig plass. På
    tvers av volum må operativsystemet kopiere heile fila og så slette originalen, og då kostar
    flyttinga akkurat like mykje som ei kopiering.
    """
    target = _volume_of(output_dir)
    return any(_volume_of(p) != target for p in source_paths(rows))


def unwritable_source(rows: list[dict], sample: int = 20) -> Optional[Path]:
    """
    Fyrste kjeldemappa som ikkje lèt seg skrive i, eller None. Ei flytting krev skriveløyve der
    filene ligg, og uttrekka frå NB kjem ofte på skriveverna område. Utan denne sjekken ville
    kvar einaste fil feile for seg, og brukaren sitje att med tusen like feilmeldingar i staden
    for éi som seier kva som er gale. Me prøver eit avgrensa utval mapper, sidan ei køyring kan
    ha tusenvis av dei, og eit skriveverna uttrekk er skriveverna heile vegen.
    """
    seen: set[Path] = set()
    for path in source_paths(rows):
        folder = path.parent
        if folder in seen:
            continue
        seen.add(folder)
        probe = folder / ".nbr-skrivetest"
        try:
            with open(probe, "wb"):
                pass
            probe.unlink()
        except OSError:
            return folder
        if len(seen) >= sample:
            break
    return None


def human_bytes(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def free_space(output_dir: Path) -> int:
    """Ledig plass der ut-mappa skal liggje. Mappa treng ikkje finnast enno; då spør me næraste
    forelder som finst."""
    probe = Path(output_dir)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def missing_space(rows: list[dict], output_dir: Path, margin: float = 0.02) -> Optional[tuple[int, int]]:
    """
    Returnerer (trengst, ledig) når det ikkje er plass til kopien, elles None. Eit skann er
    eit par på rundt 630 MB, så nokre tusen bilete blir fleire terabyte. Går disken full
    midtvegs, står brukaren att med ei halv ut-mappe og ei avbroten køyring.
    """
    needed = total_bytes(rows)
    free = free_space(output_dir)
    return (needed, free) if needed * (1 + margin) > free else None


def _manual_note(row: dict, reason: str, copied_to: str) -> dict:
    """Ei rad til lista over bilete som treng handarbeid, med grunnen til at dei hamna der."""
    return {
        "original_jpg": row.get("original_jpg", ""),
        "matched_tiff": row.get("matched_tiff", ""),
        "status": row.get("status", ""),
        "grunngjeving": reason,
        "kopiert_til": copied_to,
    }


def will_be_renamed(row: dict) -> bool:
    """
    Sant når rada får nytt namn i ut-mappa. Alt anna hamnar i _manuell med originalnamnet.
    Same regel blir brukt av oppsummeringa som blir vist før køyringa, slik at tala brukaren
    stadfestar er dei same som køyringa faktisk gjer.
    """
    return row.get("status") == STATUS_OK and bool(row.get("new_basename"))


def execute_rows(
    rows: list[dict],
    output_dir: Path,
    move: bool = False,
    overwrite: bool = False,
    organize_by_year: bool = False,
    on_progress: Optional[Callable[[int, int, dict], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> dict:
    """Kopierer/omdøyper etter rapport-radene. Returnerer statistikk og sti til manuell-lista."""
    output_dir = Path(output_dir)
    manual_root = output_dir / "_manuell"
    stats = {"omdøypt": 0, "manuell": 0, "konflikt": 0, "feil": 0}
    manual_rows: list[dict] = []
    total = len(rows)

    for idx, row in enumerate(rows, 1):
        if should_stop and should_stop():
            break

        # Éi fil som ikkje lèt seg kopiere skal ikkje stoppe dei tusen som står att. Ho blir
        # talt som feil og hamnar i manuell-lista med grunnen, slik at brukaren kan ta dei
        # etterpå i staden for å køyre alt om igjen.
        try:
            jpg = Path(row["original_jpg"])
            tiff = Path(row["matched_tiff"]) if row.get("matched_tiff") else None
            status = row["status"]

            if will_be_renamed(row):
                target_dir = output_dir / row["year"] if (organize_by_year and row.get("year")) else output_dir
                base = row["new_basename"]
                name = base + jpg.suffix.lower()
                res = _place_file(jpg, target_dir / name, move, overwrite)
                if res == "konflikt":
                    stats["konflikt"] += 1
                    manual_rows.append(
                        _manual_note(row, f"{name} låg alt i {target_dir}, så fila vart ikkje kopiert.", "")
                    )
                else:
                    if tiff and tiff.exists():
                        _place_file(tiff, target_dir / (base + tiff.suffix.lower()), move, overwrite)
                    stats["omdøypt"] += 1
            else:
                sub = manual_root / status
                res = _place_file(jpg, sub / jpg.name, move, overwrite)
                if res == "konflikt":
                    stats["konflikt"] += 1
                    manual_rows.append(
                        _manual_note(row, f"{jpg.name} låg alt i {sub}, så fila vart ikkje kopiert.", "")
                    )
                else:
                    if tiff and tiff.exists():
                        _place_file(tiff, sub / tiff.name, move, overwrite)
                    stats["manuell"] += 1
                    manual_rows.append(
                        _manual_note(row, reason_for(status, row.get("error", "")), str(sub))
                    )
        except Exception as exc:  # noqa: BLE001 - éi fil skal ikkje stoppe heile køyringa
            stats["feil"] += 1
            manual_rows.append(_manual_note(row, f"Klarte ikkje kopiere fila: {type(exc).__name__}: {exc}", ""))

        if on_progress:
            on_progress(idx, total, row)

    manual_list = manual_root / "uidentifiserte.csv"
    if manual_rows:
        write_manual_list(manual_list, manual_rows)

    stats["manual_list"] = str(manual_list) if manual_rows else ""
    return stats
