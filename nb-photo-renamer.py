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
    STATUS_REVIEW_NO_ID,
    STATUS_REVIEW_UNEXPECTED,
    OcrConfig,
    build_engine,
    classify,
    find_jpgs,
    find_matching_tiff,
    ocr_image,
    reason_for,
)
from nbrenamer import pipeline
from nbrenamer.report import (
    manual_list_path_for,
    open_report_writer,
    read_processed,
    read_rows,
    write_manual_list,
)


def cmd_discover(args):
    input_dir = Path(args.input_dir)
    report = Path(args.report)
    tiff_dir = Path(args.tiff_dir) if args.tiff_dir else None

    jpgs = find_jpgs(input_dir)
    if not jpgs:
        print(f"Fann ingen .jpg under {input_dir}", file=sys.stderr)
        return 1

    processed = read_processed(report) if args.resume else set()
    todo = [p for p in jpgs if str(p) not in processed]
    print(f"{len(jpgs)} jpg totalt, {len(processed)} alt handsama, {len(todo)} att å gjere.", flush=True)
    if not todo:
        print("Ingenting å gjere.")
        return 0

    workers = args.workers
    if args.device == "gpu" and workers > 1:
        print("GPU brukar éin prosess; set workers=1.", flush=True)
        workers = 1

    f, writer = open_report_writer(report, args.resume)
    counts = {STATUS_OK: 0, STATUS_REVIEW_NO_ID: 0, STATUS_REVIEW_UNEXPECTED: 0, STATUS_ERROR: 0}
    manual_rows: list[dict] = []

    def on_row(row: dict, i: int) -> None:
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
        print(f"[{i}/{len(todo)}] {Path(row['original_jpg']).name}: {row['status']} {row['foto_id']}", flush=True)

    init_primitives = (
        args.id_pattern, args.max_dim, args.rotations, args.autocontrast, args.prefix, args.device, args.gpu_id,
    )
    t0 = time.perf_counter()
    try:
        if workers <= 1:
            engine, actual = build_engine(args.device, args.gpu_id)
            print(f"OCR-motor: {actual.upper()}", flush=True)
            cfg = OcrConfig.make(args.id_pattern, args.max_dim, args.rotations, args.autocontrast, args.prefix)
            pipeline.run_discover_sequential(todo, engine, tiff_dir, cfg, on_row)
        else:
            pipeline.run_discover_multiprocess(todo, tiff_dir, init_primitives, on_row, workers)
    finally:
        f.close()

    manual_list = manual_list_path_for(report)
    write_manual_list(manual_list, manual_rows)

    dt = time.perf_counter() - t0
    print("\n" + "=" * 60)
    print(f"Ferdig på {dt:.1f}s ({dt / max(len(todo), 1):.2f}s/bilete).")
    print(f"  ok:                 {counts.get(STATUS_OK, 0)}")
    print(f"  manuell (ingen id): {counts.get(STATUS_REVIEW_NO_ID, 0)}")
    print(f"  manuell (uventa):   {counts.get(STATUS_REVIEW_UNEXPECTED, 0)}")
    print(f"  feil:               {counts.get(STATUS_ERROR, 0)}")
    print(f"Rapport: {report}")
    if manual_rows:
        print(f"Liste over uidentifiserte: {manual_list} ({len(manual_rows)} bilete)")
    return 0


def cmd_execute(args):
    report = Path(args.report)
    if not report.exists():
        print(f"Rapportfila finst ikkje: {report}", file=sys.stderr)
        return 1
    rows = read_rows(report)
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

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
