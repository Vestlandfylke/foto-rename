# ABOUTME: Samanliknar to rapportar frå same materiale og finn filene der OCR-en las ulikt.
# ABOUTME: Dette er lista over skjøre bilete: dei ein må sjå på når innstillingar eller motor endrar seg.
from __future__ import annotations

from pathlib import Path

ULIK_ID = "ulik id"
BERRE_A = "berre A las id"
BERRE_B = "berre B las id"
MANGLAR_I_B = "ikkje med i B"
MANGLAR_I_A = "ikkje med i A"
ULIK_STATUS = "same id, ulik status"
ULIK_RETNING = "same id, ulik retning"

# Rekkjefølgja er den ein vil lese dei i: ulike ID-ar er farlege, ulik retning er berre
# interessant. Oppsummeringa blir vist i denne rekkjefølgja.
AVVIK = [ULIK_ID, BERRE_A, BERRE_B, MANGLAR_I_B, MANGLAR_I_A, ULIK_STATUS, ULIK_RETNING]


def _key(row: dict) -> str:
    return str(Path(row.get("original_jpg", "")))


def _classify(a: dict | None, b: dict | None) -> str:
    """
    Kva slags avvik dette er, eller tom streng når dei to køyringane er samde.

    ID-en avgjer først, for han er det som blir filnamnet. Er ID-ane like, er ulik status eller
    ulik retning verdt å vite om, men det endrar ikkje resultatet: eit bilete som blei lese på 90
    grader i den eine køyringa og på 270 i den andre har fått same namn likevel.
    """
    if b is None:
        return MANGLAR_I_B
    if a is None:
        return MANGLAR_I_A
    id_a, id_b = a.get("foto_id", ""), b.get("foto_id", "")
    if id_a != id_b:
        if id_a and id_b:
            return ULIK_ID
        return BERRE_A if id_a else BERRE_B
    if a.get("status", "") != b.get("status", ""):
        return ULIK_STATUS
    if (a.get("rotation", "") or "") != (b.get("rotation", "") or ""):
        return ULIK_RETNING
    return ""


def compare_reports(rows_a: list[dict], rows_b: list[dict]) -> tuple[list[dict], dict]:
    """
    (avviksrader, oppsummering) for to rapportar over det same materialet.

    Berre avvika blir returnerte. Ei liste over dei tolv tusen filene som var like er ingen
    hjelp; lista over dei sju som ikkje var det, er heile poenget.
    """
    a_by_key = {_key(r): r for r in rows_a}
    b_by_key = {_key(r): r for r in rows_b}
    alle = sorted(set(a_by_key) | set(b_by_key))

    ut: list[dict] = []
    summary = {"filer": len(alle), "felles": 0, "like": 0}
    summary.update({navn: 0 for navn in AVVIK})

    for key in alle:
        a, b = a_by_key.get(key), b_by_key.get(key)
        if a is not None and b is not None:
            summary["felles"] += 1
        avvik = _classify(a, b)
        if not avvik:
            summary["like"] += 1
            continue
        summary[avvik] += 1
        ut.append({
            "fil": key,
            "foto_id_a": (a or {}).get("foto_id", ""),
            "foto_id_b": (b or {}).get("foto_id", ""),
            "status_a": (a or {}).get("status", ""),
            "status_b": (b or {}).get("status", ""),
            "rotasjon_a": (a or {}).get("rotation", ""),
            "rotasjon_b": (b or {}).get("rotation", ""),
            "avvik": avvik,
        })
    return ut, summary


def comparison_path_for(a: Path, b: Path) -> Path:
    """Standardnamn for samanlikninga, lagd ved sida av den fyrste rapporten."""
    return a.with_name(f"{a.stem}_mot_{b.stem}.csv")
