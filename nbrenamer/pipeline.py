# ABOUTME: Orkestrering av discover (OCR av mange filer) og execute (kopier/omdøyp) for NB foto-namngivar.
# ABOUTME: Tilbyr både sekvensiell køyring (web/GPU) og multiprosess (CPU-batch via CLI), med framdrifts-callback.
from __future__ import annotations

import os
import shutil
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Callable, Optional

from . import core
from .core import OcrConfig, build_engine, process_one, reason_for, STATUS_OK
from .folders import FolderIndex, unused_tiffs, walk_folders
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


def _worker_process(jpg_str: str, tiff_str: Optional[str]) -> dict:
    tiff = Path(tiff_str) if tiff_str else None
    return process_one(_W["engine"], Path(jpg_str), _W["cfg"], tiff)


# (jpg, tif eller None). Paret er alt avgjort av mappe-indekseringa, så ingen av køyrarane
# leitar etter partnarar sjølv.
JpgPair = tuple[Path, Optional[Path]]


def run_discover_sequential(
    todo: list[JpgPair],
    engine,
    cfg: OcrConfig,
    on_row: Callable[[dict], None],
    should_stop: Optional[Callable[[], bool]] = None,
) -> None:
    for jpg, tiff in todo:
        if should_stop and should_stop():
            break
        on_row(process_one(engine, jpg, cfg, tiff))


def _submit_folder(ex: ProcessPoolExecutor, todo: list[JpgPair],
                   on_row: Callable[[dict], None]) -> None:
    """
    Sender éi mappe til bassenget og ventar på henne.

    Berre denne mappa er i lufta om gongen. Å sende inn alt på ein gong ville laga ei liste
    med eit framtidsobjekt per fil, altså titusenvis av dei, og då veks minnebruken med
    storleiken på uttrekket i staden for med storleiken på den største mappa.
    """
    futures = [
        ex.submit(_worker_process, str(jpg), str(tiff) if tiff else None)
        for jpg, tiff in todo
    ]
    for fut in as_completed(futures):
        on_row(fut.result())


# Kor mange filer ein arbeidar tek før han blir bytt ut. ONNX- og torch-sesjonar veks over
# tusenvis av bilete, og utan resirkulering ber prosessen den veksten heile køyringa. Å byggje
# motoren på nytt kostar nokre sekund, altså rundt éin prosent når kvar fil tek eit sekund.
TASKS_PER_CHILD = 200


def run_discover(
    input_dir: Path,
    tiff_dir: Optional[Path],
    cfg: OcrConfig,
    on_row: Callable[[dict], None],
    *,
    engine=None,
    workers: int = 1,
    init_primitives: Optional[tuple] = None,
    done: frozenset[str] = frozenset(),
    should_stop: Optional[Callable[[], bool]] = None,
    skip: tuple[Path, ...] = (),
    on_folder: Optional[Callable[[dict], None]] = None,
    tasks_per_child: int = TASKS_PER_CHILD,
) -> list[dict]:
    """
    Går gjennom inn-mappa mappe for mappe, les det som står att, og returnerer mapperekneskapen.

    Éi mappe om gongen er det som gjer at minnebruken blir sett av den største mappa og ikkje
    av kor stort uttrekket er, og at kvar mappe kan gjerast opp mot disken med ein gong.
    TIFF-ar utan JPEG blir aldri lesne, men dei får rad, slik at dei ikkje forsvinn ut av
    rekneskapen.
    """
    stopped = (lambda: False) if should_stop is None else should_stop
    counter = _RowCounter(on_row)
    accounts: list[dict] = []
    used_tiffs: set[Path] = set()

    def make_pool() -> ProcessPoolExecutor:
        return ProcessPoolExecutor(max_workers=workers, initializer=_worker_init,
                                   initargs=init_primitives,
                                   max_tasks_per_child=tasks_per_child or None)

    pool = None
    if workers > 1:
        if init_primitives is None:
            raise ValueError("init_primitives må vere med når workers > 1")
        pool = make_pool()
    try:
        for index in walk_folders(input_dir, tiff_dir, skip):
            if stopped():
                break
            before = counter.n
            # TIFF-ane utan partnar fyrst, slik at dei står øvst i si eiga mappe i rapporten.
            for tiff in sorted(index.orphan_tiff.values()):
                if str(tiff) not in done:
                    counter(core.orphan_tiff_row(tiff))
            pairs = index.jpg_pairs()
            used_tiffs.update(tif for _jpg, tif in pairs if tif is not None)
            todo = [(jpg, tif) for jpg, tif in pairs if str(jpg) not in done]
            note = ""
            try:
                if pool is not None:
                    _submit_folder(pool, todo, counter)
                else:
                    run_discover_sequential(todo, engine, cfg, counter, should_stop)
            except BrokenProcessPool as exc:
                # Ein arbeidar døydde, typisk fordi operativsystemet tok han for minnebruk på
                # ei uvanleg stor fil. Utan dette ville éi vond fil drepe heile køyringa og
                # ta med seg dei mappene som stod att. Mappa blir merkt, bassenget bygd på
                # nytt, og resten held fram. Det som mangla kan hentast med gjenopptaking.
                note = f"Arbeidarprosess døydde: {type(exc).__name__}"
                pool.shutdown(wait=False, cancel_futures=True)
                pool = make_pool()
            account = folder_account(index, input_dir, counter.n - before, done, note)
            accounts.append(account)
            if on_folder:
                on_folder(account)

        if tiff_dir is not None and not stopped():
            # Ligg TIFF-ane i ei eiga mappe, kan ingen vite kven som er foreldrelaus før
            # heile treet er gjennomgått og alle partnarane er kjende.
            extra = unused_tiffs(tiff_dir, used_tiffs)
            before = counter.n
            for tiff in extra:
                if str(tiff) not in done:
                    counter(core.orphan_tiff_row(tiff))
            if extra:
                accounts.append({
                    "mappe": str(tiff_dir),
                    "jpg": 0, "tiff": len(extra), "par": 0,
                    "tiff_utan_jpg": len(extra), "jpg_utan_tiff": 0,
                    "rader": counter.n - before,
                    "gjer_opp": "ja",
                    "merknad": f"{len(extra)} tiff utan jpg i eiga tiff-mappe",
                })
    finally:
        if pool is not None:
            pool.shutdown(wait=True)
    return accounts


class _RowCounter:
    """Tel radene på veg ut, slik at kvar mappe kan gjerast opp mot filene som låg der."""

    def __init__(self, on_row: Callable[[dict], None]):
        self._on_row = on_row
        self.n = 0

    def __call__(self, row: dict) -> None:
        self.n += 1
        self._on_row(row)


def folder_account(index: FolderIndex, input_dir: Path, rows_written: int,
                   done: frozenset[str], note: str = "") -> dict:
    """
    Ei rad i mapperekneskapen: kva som låg i mappa, og kor mange rader ho fekk.

    `gjer_opp` er ja når kvar JPEG og kvar TIFF utan partnar har fått ei rad. TIFF-ane i par
    er gjorde greie for gjennom rada til JPEG-en sin, der dei står i `matched_tiff`. Ved
    gjenopptak tel radene frå den førre køyringa med; elles ville alt sett ut som om det mangla.
    """
    expected = index.n_jpg + len(index.orphan_tiff)
    from_before = sum(1 for jpg, _tif in index.jpg_pairs() if str(jpg) in done)
    from_before += sum(1 for tif in index.orphan_tiff.values() if str(tif) in done)
    accounted = rows_written + from_before
    try:
        name = str(index.path.relative_to(input_dir))
    except ValueError:
        name = str(index.path)
    notes = []
    if note:
        notes.append(note)
    if index.orphan_tiff:
        notes.append(f"{len(index.orphan_tiff)} tiff utan jpg")
    if accounted != expected:
        notes.append(f"{expected - accounted} fil(er) utan rad")
    return {
        "mappe": name,
        "jpg": index.n_jpg,
        "tiff": index.n_tiff,
        "par": len(index.paired),
        "tiff_utan_jpg": len(index.orphan_tiff),
        "jpg_utan_tiff": len(index.lone_jpg),
        "rader": accounted,
        "gjer_opp": "ja" if accounted == expected else "nei",
        "merknad": "; ".join(notes),
    }


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
