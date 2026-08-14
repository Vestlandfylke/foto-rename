# ABOUTME: Indekserer inn-mappa mappe for mappe og parar .jpg med .tif på filnamn før OCR startar.
# ABOUTME: Ein TIFF utan JPEG-partnar blir funnen her, slik at han ikkje blir usynleg for resten av appen.
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from .core import JPG_SUFFIXES, TIFF_SUFFIXES, find_matching_tiff


@dataclass
class FolderIndex:
    """
    Innhaldet i éi mappe, sortert etter kva som kan parast.

    Paringa skjer på filnamn, ikkje på innhald. Ein .tif som ikkje har ein .jpg med same
    filstamme kan ikkje få ein lesen ID, og hamnar difor i `orphan_tiff` i staden for å bli
    send gjennom OCR-en.
    """

    path: Path
    paired: dict[str, tuple[Path, Path]] = field(default_factory=dict)
    lone_jpg: dict[str, Path] = field(default_factory=dict)
    orphan_tiff: dict[str, Path] = field(default_factory=dict)

    @property
    def n_jpg(self) -> int:
        return len(self.paired) + len(self.lone_jpg)

    @property
    def n_tiff(self) -> int:
        return len(self.paired) + len(self.orphan_tiff)

    @property
    def n_files(self) -> int:
        return self.n_jpg + self.n_tiff

    @property
    def is_empty(self) -> bool:
        return self.n_files == 0

    def jpg_pairs(self) -> list[tuple[Path, Optional[Path]]]:
        """(jpg, tif eller None) for alt som skal gjennom OCR, i namnerekkjefølgje."""
        pairs: list[tuple[Path, Optional[Path]]] = [
            (jpg, tif) for _stem, (jpg, tif) in sorted(self.paired.items())
        ]
        pairs.extend((jpg, None) for _stem, jpg in sorted(self.lone_jpg.items()))
        return sorted(pairs, key=lambda p: p[0].name)


def index_folder(folder: Path, tiff_dir: Optional[Path] = None) -> FolderIndex:
    """
    Les éi mappe, ikkje undermappene, og par filene på filstamme.

    Ingen av filene blir opna. `tiff_dir` er for materiale der TIFF-ane ligg i ei eiga mappe;
    då blir partnaren søkt opp der for dei JPEG-ane som ikkje har han i si eiga mappe.
    """
    jpgs: dict[str, Path] = {}
    tiffs: dict[str, Path] = {}

    with os.scandir(folder) as entries:
        for entry in entries:
            if not entry.is_file(follow_symlinks=False):
                continue
            p = Path(entry.path)
            suffix = p.suffix.lower()
            if suffix in JPG_SUFFIXES:
                jpgs.setdefault(p.stem, p)
            elif suffix in TIFF_SUFFIXES:
                tiffs.setdefault(p.stem, p)

    index = FolderIndex(path=folder)
    for stem, jpg in jpgs.items():
        tiff = tiffs.get(stem)
        if tiff is None and tiff_dir is not None:
            tiff = find_matching_tiff(jpg, tiff_dir)
        if tiff is None:
            index.lone_jpg[stem] = jpg
        else:
            index.paired[stem] = (jpg, tiff)
    index.orphan_tiff = {s: t for s, t in tiffs.items() if s not in jpgs}
    return index


def walk_folders(root: Path, tiff_dir: Optional[Path] = None,
                 skip: tuple[Path, ...] = ()) -> Iterator[FolderIndex]:
    """
    Gir éin FolderIndex om gongen, nedover heile treet.

    Generator, ikkje liste: eit uttrekk frå NB kan ha fleire hundre undermapper med titusenvis
    av filer, og då skal ikkje heile fillista finnast i minnet før arbeidet startar.

    `skip` er mapper som skal haldast utanfor, oppgitt som stiar og ikkje som namnemønster.
    Det er ut-mappa når ho ligg inne i inn-mappa, og TIFF-mappa, som blir gjennomgått for seg
    til slutt. Å hoppe over på namn ville vore den same stille utelatinga me prøver å unngå:
    ei kjeldemappe kan godt heite noko som liknar på våre eigne.
    """
    root = Path(root)
    skipped = {Path(p).resolve() for p in skip}
    if tiff_dir is not None:
        skipped.add(Path(tiff_dir).resolve())
    for dirpath, dirnames, _files in os.walk(root):
        here = Path(dirpath)
        dirnames.sort()
        dirnames[:] = [d for d in dirnames if (here / d).resolve() not in skipped]
        if here.resolve() in skipped:
            continue
        index = index_folder(here, tiff_dir)
        if not index.is_empty:
            yield index


def unused_tiffs(tiff_dir: Path, used: set[Path]) -> list[Path]:
    """
    TIFF-ane i ei eiga TIFF-mappe som ingen JPEG peika på. Same tanken som foreldrelause
    TIFF-ar i ei blanda mappe, men han kan fyrst avgjerast når heile treet er gjennomgått.
    """
    brukte = {p.resolve() for p in used}
    out = []
    with os.scandir(tiff_dir) as entries:
        for entry in entries:
            if not entry.is_file(follow_symlinks=False):
                continue
            p = Path(entry.path)
            if p.suffix.lower() in TIFF_SUFFIXES and p.resolve() not in brukte:
                out.append(p)
    return sorted(out)


def count_work(root: Path, tiff_dir: Optional[Path] = None, skip: tuple[Path, ...] = (),
               done: frozenset[str] = frozenset()) -> tuple[int, int, int]:
    """
    (jpg, foreldrelause tiff, att å gjere) i heile treet.

    Framdriftsvisinga treng eit totaltal før arbeidet startar, og dette er ein rein
    katalog-gjennomgang utan å opne filer: sekund, mot timar for sjølve lesinga. `done` er
    filene som alt står i rapporten, slik at eit gjenopptak reknar rett.
    """
    n_jpg = 0
    n_orphan = 0
    n_todo = 0
    for index in walk_folders(root, tiff_dir, skip):
        n_jpg += index.n_jpg
        n_orphan += len(index.orphan_tiff)
        n_todo += sum(1 for jpg, _tif in index.jpg_pairs() if str(jpg) not in done)
        n_todo += sum(1 for tif in index.orphan_tiff.values() if str(tif) not in done)
    return n_jpg, n_orphan, n_todo
