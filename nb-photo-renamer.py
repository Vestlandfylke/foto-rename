# ABOUTME: CLI for NB foto-namngivar. Tynn wrapper over nbrenamer-pakken (to-fase: discover -> execute, pluss test).
# ABOUTME: Gir re-digitaliserte NB-fotofiler nye ID-baserte namn etter namngivingsregelen, sjå README.
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from nbrenamer import core
from nbrenamer.core import (
    DEFAULT_ID_PATTERN,
    DEFAULT_MAX_DIM,
    DEFAULT_PREFIX,
    DEFAULT_ROTATIONS,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_ORPHAN_TIFF,
    STATUS_REVIEW_NO_ID,
    STATUS_REVIEW_UNEXPECTED,
    OcrConfig,
    build_engine,
    classify,
    find_matching_tiff,
    ocr_image,
    reason_for,
)
from nbrenamer import pipeline
from nbrenamer.compare import AVVIK, compare_reports, comparison_path_for
from nbrenamer.folders import count_work
from nbrenamer.report import (
    folder_list_path_for,
    manual_list_path_for,
    open_report_writer,
    read_processed,
    read_rows,
    write_comparison,
    write_folder_list,
    write_manual_list,
)


def cmd_discover(args):
    input_dir = Path(args.input_dir)
    report = Path(args.report)
    tiff_dir = Path(args.tiff_dir) if args.tiff_dir else None

    processed = frozenset(read_processed(report)) if args.resume else frozenset()
    n_jpg, n_orphan, n_todo = count_work(input_dir, tiff_dir, done=processed)
    if not n_jpg and not n_orphan:
        print(f"Fann ingen .jpg eller .tif under {input_dir}", file=sys.stderr)
        return 1

    print(f"{n_jpg} jpg totalt, {len(processed)} alt handsama, {n_todo} att å gjere.", flush=True)
    if n_orphan:
        print(f"{n_orphan} tiff utan jpg. Dei blir ikkje lesne, men dei får rad.", flush=True)
    if not n_todo:
        print("Ingenting å gjere.")
        return 0

    workers = args.workers
    if args.device == "gpu" and workers > 1:
        print("GPU brukar éin prosess; set workers=1.", flush=True)
        workers = 1

    f, writer = open_report_writer(report, args.resume)
    counts: dict[str, int] = {}
    manual_rows: list[dict] = []
    done = 0

    def on_row(row: dict) -> None:
        nonlocal done
        done += 1
        writer.writerow(row)
        f.flush()
        counts[row["status"]] = counts.get(row["status"], 0) + 1
        if row["status"] != STATUS_OK:
            manual_rows.append(
                {
                    "original_jpg": row["original_jpg"],
                    "matched_tiff": row["matched_tiff"],
                    "status": row["status"],
                    "grunngjeving": reason_for(row["status"], row["error"]),
                }
            )
        print(f"[{done}/{n_todo}] {Path(row['original_jpg']).name}: {row['status']} {row['foto_id']}", flush=True)

    init_primitives = (
        args.id_pattern, args.max_dim, args.rotations, args.autocontrast, args.prefix, args.device, args.gpu_id,
    )
    cfg = OcrConfig.make(args.id_pattern, args.max_dim, args.rotations, args.autocontrast, args.prefix)
    engine = None
    if workers <= 1:
        engine, actual = build_engine(args.device, args.gpu_id)
        print(f"OCR-motor: {actual.upper()}", flush=True)

    def on_folder(account: dict) -> None:
        if account["gjer_opp"] == "nei":
            print(f"  ADVARSEL mappa {account['mappe']} går ikkje opp: {account['merknad']}", flush=True)

    t0 = time.perf_counter()
    try:
        folder_rows = pipeline.run_discover(
            input_dir, tiff_dir, cfg, on_row,
            engine=engine, workers=workers, init_primitives=init_primitives, done=processed,
            on_folder=on_folder,
        )
    finally:
        f.close()

    manual_list = manual_list_path_for(report)
    write_manual_list(manual_list, manual_rows)
    folder_list = folder_list_path_for(report)
    write_folder_list(folder_list, folder_rows)
    unbalanced = [r for r in folder_rows if r["gjer_opp"] == "nei"]

    dt = time.perf_counter() - t0
    print("\n" + "=" * 60)
    print(f"Ferdig på {dt:.1f}s ({dt / max(n_todo, 1):.2f}s/bilete).")
    print(f"  ok:                 {counts.get(STATUS_OK, 0)}")
    print(f"  manuell (ingen id): {counts.get(STATUS_REVIEW_NO_ID, 0)}")
    print(f"  manuell (uventa):   {counts.get(STATUS_REVIEW_UNEXPECTED, 0)}")
    print(f"  tiff utan jpg:      {counts.get(STATUS_ORPHAN_TIFF, 0)}")
    print(f"  feil:               {counts.get(STATUS_ERROR, 0)}")
    print(f"Rapport: {report}")
    if manual_rows:
        print(f"Liste over uidentifiserte: {manual_list} ({len(manual_rows)} bilete)")
    print(f"Mapperekneskap: {folder_list} ({len(folder_rows)} mapper)")
    if unbalanced:
        print(f"  {len(unbalanced)} mappe(r) går ikkje opp. Sjå kolonnen gjer_opp.")
    return 0


def cmd_execute(args):
    report = Path(args.report)
    if not report.exists():
        print(f"Rapportfila finst ikkje: {report}", file=sys.stderr)
        return 1
    rows = read_rows(report)
    # Ei flytting krev skriveløyve der originalane ligg, elles feilar kvar einaste fil for seg.
    if args.move:
        locked = pipeline.unwritable_source(rows)
        if locked:
            print(f"Kan ikkje flytte originalane: {locked} er skriveverna.", file=sys.stderr)
            return 1
    # Ei flytting innanfor same volum treng ikkje ekstra plass. På tvers av volum blir filene
    # kopierte og så sletta, og då gjeld plasskravet som ved ei vanleg kopiering.
    if not args.move or pipeline.crosses_volume(rows, Path(args.output_dir)):
        shortfall = pipeline.missing_space(rows, Path(args.output_dir))
        if shortfall:
            needed, free = shortfall
            print(
                f"Ikkje nok plass i {args.output_dir}. Kopien treng "
                f"{pipeline.human_bytes(needed)}, men berre {pipeline.human_bytes(free)} er ledig.",
                file=sys.stderr,
            )
            return 1
    stats = pipeline.execute_rows(
        rows,
        Path(args.output_dir),
        move=args.move,
        overwrite=args.overwrite,
        organize_by_year=args.organize_by_year,
    )
    print("\n" + "=" * 60)
    print(f"Omdøypt (jpg+tif):  {stats['omdøypt']}")
    print(f"Til manuell mappe:  {stats['manuell']}")
    print(f"Konfliktar:         {stats['konflikt']}")
    print(f"Feil:               {stats['feil']}")
    if stats.get("tiff_feil"):
        print(f"TIFF-ar utan plass: {stats['tiff_feil']} (jpg-en kom med, tif-en ikkje)")
    print(f"Utdata i:           {args.output_dir}")
    if stats.get("manual_list"):
        print(f"Liste over uidentifiserte: {stats['manual_list']}")
    return 0


def cmd_test(args):
    engine, actual = build_engine(args.device, args.gpu_id)
    print(f"OCR-motor: {actual.upper()}\n", flush=True)
    cfg = OcrConfig.make(args.id_pattern, args.max_dim, args.rotations, args.autocontrast, args.prefix)
    jpg = Path(args.file)
    print(f"OCR av {jpg.name} ...\n", flush=True)
    t0 = time.perf_counter()
    outcome = ocr_image(engine, jpg, cfg)
    cls = classify(outcome, cfg.prefix)
    tiff = find_matching_tiff(jpg, None)
    dt = time.perf_counter() - t0

    print(f"Full OCR-tekst:\n  {outcome.text}\n")
    print(f"Rotasjon som gav treff: {outcome.rotation}")
    print(f"Rå ID i motiv:          {outcome.raw_id}")
    print(f"Status:                 {cls.status}")
    if cls.error:
        print(f"Merknad:                {cls.error}")
    print(f"Foto-ID (nytt namn):    {cls.foto_id}")
    print(f"År:                     {cls.year}")
    print(f"Matchande .tif:         {tiff}")
    print(f"\nTid: {dt:.2f}s")
    return 0


def cmd_compare(args):
    """
    Samanliknar to rapportar over det same materialet og skriv ut kva som skil dei.

    Dette er kontrollen som gjer det forsvarleg å endre noko som påverkar lesinga: ny motor, ny
    CUDA-versjon, andre retningar, autokontrast av eller på. Ein køyrer discover to gonger til to
    rapportar, og ser så på dei filene der dei to ikkje les det same. Ingen les tolv tusen rader,
    men alle kan sjå på sju.
    """
    a, b = Path(args.a), Path(args.b)
    for fil in (a, b):
        if not fil.exists():
            print(f"Rapportfila finst ikkje: {fil}", file=sys.stderr)
            return 1

    avvik, oppsummering = compare_reports(read_rows(a), read_rows(b))
    print(f"A: {a}")
    print(f"B: {b}\n")
    print(f"Filer i alt:        {oppsummering['filer']}")
    print(f"I begge køyringane: {oppsummering['felles']}")
    print(f"Les likt:           {oppsummering['like']}")
    for namn in AVVIK:
        if oppsummering[namn]:
            print(f"  {namn + ':':<22}{oppsummering[namn]}")

    if not avvik:
        print("\nDei to køyringane les identisk på alle filene.")
        return 0

    ut = Path(args.out) if args.out else comparison_path_for(a, b)
    write_comparison(ut, avvik)
    print(f"\n{len(avvik)} avvik. Skrivne til: {ut}")
    for rad in avvik[:10]:
        print(f"  {Path(rad['fil']).name:<44} {rad['avvik']:<22} "
              f"{rad['foto_id_a'] or '-'} / {rad['foto_id_b'] or '-'}")
    if len(avvik) > 10:
        print(f"  ... og {len(avvik) - 10} fleire i fila.")
    return 0


def add_ocr_args(p):
    p.add_argument("--id-pattern", default=DEFAULT_ID_PATTERN, help="Regex med to grupper: taldel og sekvensdel")
    p.add_argument("--prefix", default=DEFAULT_PREFIX, help="Prefiks i nytt filnamn")
    p.add_argument("--max-dim", type=int, default=DEFAULT_MAX_DIM, help="Lengste biletkant før OCR")
    p.add_argument("--rotations", default=DEFAULT_ROTATIONS, help="Rotasjonar som blir prøvde, t.d. 0,90,270")
    p.add_argument("--autocontrast", action="store_true", default=True, help="Autokontrast (på som standard)")
    p.add_argument("--no-autocontrast", dest="autocontrast", action="store_false")
    p.add_argument("--device", choices=["gpu", "cpu"], default="gpu", help="OCR på GPU (torch-CUDA) eller CPU (ONNX)")
    p.add_argument("--gpu-id", type=int, default=0)


def build_parser():
    parser = argparse.ArgumentParser(description="Gir NB-fotofiler nye ID-baserte namn med lokal OCR.")
    sub = parser.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover", help="OCR alle bilete og skriv CSV-rapport (ingen filer blir flytta)")
    d.add_argument("--input-dir", required=True)
    d.add_argument("--report", default="report.csv")
    d.add_argument("--tiff-dir", default=None, help="Eiga mappe for .tif viss ulik input-dir")
    d.add_argument("--workers", type=int, default=1, help="Parallelle prosessar (berre CPU)")
    d.add_argument("--resume", action="store_true", help="Hopp over filer som alt står i rapporten")
    add_ocr_args(d)
    d.set_defaults(func=cmd_discover)

    e = sub.add_parser("execute", help="Les (eventuelt redigert) rapport og kopier/omdøyp filer")
    e.add_argument("--report", default="report.csv")
    e.add_argument("--output-dir", required=True)
    e.add_argument("--move", action="store_true", help="Flytt i staden for å kopiere")
    e.add_argument("--overwrite", action="store_true", help="Skriv over eksisterande målfiler")
    e.add_argument("--organize-by-year", action="store_true", help="Legg ok-filer i undermapper per år")
    e.set_defaults(func=cmd_execute)

    t = sub.add_parser("test", help="Køyr OCR på éi fil og skriv ut alt")
    t.add_argument("--file", required=True)
    add_ocr_args(t)
    t.set_defaults(func=cmd_test)

    c = sub.add_parser("compare", help="Samanlikn to rapportar og finn filene som blei lesne ulikt")
    c.add_argument("--a", required=True, help="Fyrste rapporten")
    c.add_argument("--b", required=True, help="Andre rapporten")
    c.add_argument("--out", default=None, help="Kvar avvika skal skrivast (standard: ved sida av A)")
    c.set_defaults(func=cmd_compare)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
