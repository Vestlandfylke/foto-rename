# ABOUTME: CSV-hjelparar for rapporten og lista over uidentifiserte bilete.
# ABOUTME: Brukt av både discover (skriv rapport + liste) og execute (les rapport, skriv liste).
from __future__ import annotations

import csv
import os
from pathlib import Path

from .core import CSV_FIELDS, MANUAL_LIST_FIELDS


def read_processed(report: Path) -> set[str]:
    if not report.exists():
        return set()
    done = set()
    with report.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            done.add(row["original_jpg"])
    return done


def read_rows(report: Path) -> list[dict]:
    with report.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_rows(report: Path, rows: list[dict]) -> None:
    """
    Skriv heile rapporten på nytt, atomisk. Ei vanleg skriving ville tømt fila fyrst, og eit
    avbrot der, full disk eller straumbrot, ville øydelagt ei OCR-køyring som kan ha teke
    timar. Difor går alt til ei nabofil som blir bytt inn til slutt.
    """
    report.parent.mkdir(parents=True, exist_ok=True)
    tmp = report.with_name(report.name + ".ny")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, report)


def open_report_writer(report: Path, resume: bool):
    """Opnar rapporten for skriving (append ved resume), returnerer (fil, writer)."""
    report.parent.mkdir(parents=True, exist_ok=True)
    exists = report.exists()
    mode = "a" if (resume and exists) else "w"
    f = report.open(mode, encoding="utf-8", newline="")
    writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
    if mode == "w":
        writer.writeheader()
        f.flush()
    return f, writer


def write_manual_list(path: Path, rows: list[dict]) -> None:
    """Skriv ei CSV-liste over bilete som ikkje kunne namngivast automatisk, med grunngjeving."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANUAL_LIST_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in MANUAL_LIST_FIELDS})


def manual_list_path_for(report: Path) -> Path:
    return report.with_name(report.stem + "_uidentifiserte.csv")
