# ABOUTME: CSV-hjelparar for rapporten og lista over uidentifiserte bilete.
# ABOUTME: Brukt av både discover (skriv rapport + liste) og execute (les rapport, skriv liste).
from __future__ import annotations

import csv
import os
from pathlib import Path

from .core import COMPARE_FIELDS, CSV_FIELDS, FOLDER_LIST_FIELDS, MANUAL_LIST_FIELDS

# Rapportane blir opna i Excel, og Excel på norsk Windows deler kolonnar på semikolon.
# Han les fila som UTF-8 berre når ho startar med eit BOM, som "utf-8-sig" legg inn;
# utan det blir æ, ø og å feil.
DELIMITER = ";"
ENCODING = "utf-8-sig"


def _open_read(report: Path):
    """Les med "utf-8-sig", som fjernar eit BOM om det finst og elles er identisk med utf-8."""
    return report.open("r", encoding="utf-8-sig", newline="")


def _delimiter_in(report: Path) -> str:
    """
    Kva skiljeteikn fila faktisk brukar. Rapportar frå eldre køyringar har komma, og dei
    skal framleis kunne lesast. Overskriftslinja avgjer, for feltnamna inneheld korkje
    semikolon eller komma.
    """
    with _open_read(report) as f:
        header = f.readline()
    return DELIMITER if header.count(DELIMITER) >= header.count(",") else ","


def read_processed(report: Path) -> set[str]:
    if not report.exists():
        return set()
    delimiter = _delimiter_in(report)
    done = set()
    with _open_read(report) as f:
        for row in csv.DictReader(f, delimiter=delimiter):
            done.add(row["original_jpg"])
    return done


def read_rows(report: Path) -> list[dict]:
    delimiter = _delimiter_in(report)
    with _open_read(report) as f:
        return list(csv.DictReader(f, delimiter=delimiter))


def write_rows(report: Path, rows: list[dict]) -> None:
    """
    Skriv heile rapporten på nytt, atomisk. Ei vanleg skriving ville tømt fila fyrst, og eit
    avbrot der, full disk eller straumbrot, ville øydelagt ei OCR-køyring som kan ha teke
    timar. Difor går alt til ei nabofil som blir bytt inn til slutt.
    """
    report.parent.mkdir(parents=True, exist_ok=True)
    tmp = report.with_name(report.name + ".ny")
    with tmp.open("w", encoding=ENCODING, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, delimiter=DELIMITER)
        writer.writeheader()
        writer.writerows(rows)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, report)


def open_report_writer(report: Path, resume: bool):
    """Opnar rapporten for skriving (append ved resume), returnerer (fil, writer)."""
    report.parent.mkdir(parents=True, exist_ok=True)
    append = resume and report.exists()
    if append:
        # Fila har alt eit BOM, og "utf-8-sig" ville lagt inn eitt nytt midt i henne.
        # Skiljeteiknet må vere det same som resten av fila brukar.
        delimiter = _delimiter_in(report)
        f = report.open("a", encoding="utf-8", newline="")
    else:
        delimiter = DELIMITER
        f = report.open("w", encoding=ENCODING, newline="")
    writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, delimiter=delimiter)
    if not append:
        writer.writeheader()
        f.flush()
    return f, writer


def write_manual_list(path: Path, rows: list[dict]) -> None:
    """Skriv ei CSV-liste over bilete som ikkje kunne namngivast automatisk, med grunngjeving."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=ENCODING, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANUAL_LIST_FIELDS, delimiter=DELIMITER)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in MANUAL_LIST_FIELDS})


def manual_list_path_for(report: Path) -> Path:
    return report.with_name(report.stem + "_uidentifiserte.csv")


def write_folder_list(path: Path, rows: list[dict]) -> None:
    """
    Skriv rekneskapen per mappe: kor mange filer som låg der, og kor mange rader dei fekk.

    Dette er lista arkivaren kan bruke til å slå fast at ingenting er gløymt. Mapper der
    `gjer_opp` er «nei» er dei einaste ein må sjå på.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=ENCODING, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FOLDER_LIST_FIELDS, delimiter=DELIMITER)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FOLDER_LIST_FIELDS})


def folder_list_path_for(report: Path) -> Path:
    return report.with_name(report.stem + "_mapper.csv")


def write_comparison(path: Path, rows: list[dict]) -> None:
    """Skriv avvika mellom to køyringar. Tom fil med berre overskrifter tyder at dei var samde."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=ENCODING, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COMPARE_FIELDS, delimiter=DELIMITER)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in COMPARE_FIELDS})
