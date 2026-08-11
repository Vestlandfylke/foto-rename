# ABOUTME: Bake-off-harness som køyrer RapidOCR (ONNX) på testbileta frå NB-arkivet.
# ABOUTME: Skriv ut funnen identifikator (SFFf-NNNNN.NNNN), konfidens og tid per bilete.
import argparse
import re
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from rapidocr import RapidOCR

Image.MAX_IMAGE_PIXELS = None

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Fleksibelt mønster: prefiks SFF(f), bindestrek, talgruppe, punktum/komma, talgruppe.
# OCR kan lese O/o som 0, mellomrom kan snike seg inn, difor romsleg.
ID_PATTERN = re.compile(r"SFF[fF]?\s*[-\u2013]?\s*(\d{4,6})\s*[.,]\s*(\d{3,4})", re.IGNORECASE)


def load_base(path: Path, max_dim: int, autocontrast: bool) -> Image.Image:
    img = Image.open(path).convert("L").convert("RGB") if autocontrast else Image.open(path).convert("RGB")
    if autocontrast:
        img = ImageOps.autocontrast(img, cutoff=1)
    w, h = img.size
    scale = max_dim / max(w, h)
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return img


def to_bgr(img: Image.Image) -> np.ndarray:
    # RapidOCR/opencv ventar BGR.
    return np.asarray(img)[:, :, ::-1].copy()


def extract_texts(result) -> list[str]:
    txts = getattr(result, "txts", None)
    if txts is None:
        return []
    return [str(t) for t in txts]


def find_id(full_text: str):
    m = ID_PATTERN.search(full_text)
    if not m:
        return None
    return f"SFFf-{m.group(1)}.{m.group(2)}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", default=r"d:\foto-rename\Filemail.com - testfiler frå arkivet")
    ap.add_argument("--max-dim", type=int, default=2048)
    ap.add_argument("--show-text", action="store_true", help="Skriv ut all OCR-tekst per bilete")
    ap.add_argument("--rotations", default="0", help="Komma-separert liste, t.d. 0,90,270")
    ap.add_argument("--autocontrast", action="store_true", help="Auto-kontrast for falma reprofilm")
    ap.add_argument("--only", default=None, help="Berre bilete der namnet inneheld denne strengen")
    args = ap.parse_args()

    rotations = [int(r) for r in args.rotations.split(",")]

    input_dir = Path(args.input_dir)
    jpgs = sorted(input_dir.glob("*.jpg"))
    if args.only:
        jpgs = [p for p in jpgs if args.only in p.name]
    if not jpgs:
        print(f"Fann ingen .jpg i {input_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Lastar RapidOCR ...", flush=True)
    t0 = time.perf_counter()
    engine = RapidOCR()
    print(f"Modellar lasta paa {time.perf_counter() - t0:.1f}s. max-dim={args.max_dim}\n", flush=True)

    rows = []
    for path in jpgs:
        base = load_base(path, args.max_dim, args.autocontrast)
        found = None
        used_rot = None
        full = ""
        t = time.perf_counter()
        for rot in rotations:
            img = base.rotate(rot, expand=True) if rot else base
            result = engine(to_bgr(img))
            texts = extract_texts(result)
            cand_full = "  ".join(texts)
            cand = find_id(cand_full)
            if cand:
                found, used_rot, full = cand, rot, cand_full
                break
            if not full:
                full = cand_full
        dt = time.perf_counter() - t
        rows.append((path.name, found, dt))
        print(f"{path.name}")
        print(f"  ID: {found!r}   rot: {used_rot}   tid: {dt:.2f}s")
        if args.show_text:
            print(f"  TEKST: {full[:400]}")
        print(flush=True)

    print("=" * 60)
    ok = sum(1 for _, f, _ in rows if f)
    avg = sum(d for _, _, d in rows) / len(rows)
    print(f"Treff: {ok}/{len(rows)} bilete fekk ID. Snitt-tid: {avg:.2f}s/bilete")


if __name__ == "__main__":
    main()
