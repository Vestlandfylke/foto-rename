# ABOUTME: Kjernelogikk for NB foto-namngivar: OCR-motor (CPU/GPU), ID-lesing, 8/9-transformasjon og .tif-matching.
# ABOUTME: Delt mellom CLI-en (nb-photo-renamer.py) og web-backend (nbrenamer/webapp.py).
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = None

DEFAULT_ID_PATTERN = r"SFF[Ff]?\s*[-\u2013]?\s*(\d{4,6})\s*[.,]\s*(\d{2,4})"
DEFAULT_ROTATIONS = "0,90,270"
DEFAULT_MAX_DIM = 2048
DEFAULT_PREFIX = "SFFf"
TIFF_SUFFIXES = (".tif", ".tiff")
JPG_SUFFIXES = (".jpg", ".jpeg")

STATUS_OK = "ok"
STATUS_REVIEW_NO_ID = "manuell_ingen_id"
STATUS_REVIEW_UNEXPECTED = "manuell_uventa_tal"
STATUS_ERROR = "feil"

REASONS = {
    STATUS_OK: "ID lesen i motivet, og nytt namn er klart.",
    STATUS_REVIEW_NO_ID: (
        "Fann ingen SFFf-ID i motivet. Teksten er truleg uleseleg eller for falma, "
        "eller står i ein orientering som ikkje gav treff."
    ),
    STATUS_REVIEW_UNEXPECTED: (
        "ID funnen, men taldelen byrjar ikkje på 8 eller 9. Må vurderast manuelt "
        "(kan vere eit avvikande nummer eller feillesing)."
    ),
    STATUS_ERROR: "Teknisk feil under prosessering av fila.",
}

# Korte namn til grensesnittet. Kodane over er det som står i CSV-en og som filtreringa
# byggjer på; desse er berre til visning, så brukaren ikkje må velje mellom «manuell_ingen_id»
# og «manuell_uventa_tal». Rekkjefølgja her er den UI-et viser dei i.
STATUS_LABELS = {
    STATUS_OK: "Klar",
    STATUS_REVIEW_NO_ID: "Manglar ID",
    STATUS_REVIEW_UNEXPECTED: "Uventa tal",
    STATUS_ERROR: "Feil",
}

# Mønsteret eit ferdig Foto-ID skal ha: prefiks, seks til åtte siffer, punktum og to til fire
# siffer. Med vilje mildare enn 8/9-regelen i classify(), sidan eit menneske som rettar
# manuelt kan ha grunnar maskina ikkje kjenner. Grensesnittet varslar, det sperrar ikkje.
FOTO_ID_PATTERN = rf"^{DEFAULT_PREFIX}-\d{{6,8}}\.\d{{2,4}}$"
FOTO_ID_EXAMPLE = f"{DEFAULT_PREFIX}-1994207.0007"

CSV_FIELDS = [
    "original_jpg",
    "ocr_text",
    "rotation",
    "raw_id",
    "foto_id",
    "new_basename",
    "year",
    "matched_tiff",
    "status",
    "error",
]

MANUAL_LIST_FIELDS = ["original_jpg", "matched_tiff", "status", "grunngjeving", "kopiert_til"]


def reason_for(status: str, error: str = "") -> str:
    """Statisk forklaringstekst per status, med systemfeilen lagt til ved tekniske feil."""
    base = REASONS.get(status, "Ukjend status.")
    if status == STATUS_ERROR and error:
        return f"{base} ({error})"
    return base


@dataclass
class OcrConfig:
    pattern: re.Pattern
    max_dim: int = DEFAULT_MAX_DIM
    rotations: tuple[int, ...] = (0, 90, 270)
    autocontrast: bool = True
    prefix: str = DEFAULT_PREFIX

    @classmethod
    def make(cls, pattern_str=DEFAULT_ID_PATTERN, max_dim=DEFAULT_MAX_DIM,
             rotations="0,90,270", autocontrast=True, prefix=DEFAULT_PREFIX) -> "OcrConfig":
        rots = tuple(int(r) for r in str(rotations).split(",")) if isinstance(rotations, str) else tuple(rotations)
        return cls(re.compile(pattern_str, re.IGNORECASE), int(max_dim), rots, bool(autocontrast), prefix)


# ----------------------------------------------------------------------------
# OCR-motor
# ----------------------------------------------------------------------------
def gpu_available() -> bool:
    """Sjekkar om torch ser ein CUDA-GPU. Returnerer False om torch ikkje er installert."""
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def build_engine(device: str = "gpu", gpu_id: int = 0):
    """
    Lagar ein RapidOCR-instans. device='gpu' bruker torch-CUDA-motoren når den er
    tilgjengeleg, elles fell me tilbake til ONNX Runtime på CPU.
    Returnerer (engine, faktisk_device).
    """
    from rapidocr import RapidOCR

    if device == "gpu" and gpu_available():
        try:
            from rapidocr import EngineType, LangCls, LangDet, LangRec, ModelType, OCRVersion

            # Torch-motoren har PP-OCRv5 (det/rec mobile+server) og éin cls-modell.
            # PP-OCRv6/small (standard for ONNX) finst ikkje for torch, difor eksplisitt v5/mobile.
            engine = RapidOCR(
                params={
                    "Det.engine_type": EngineType.TORCH,
                    "Det.ocr_version": OCRVersion.PPOCRV5,
                    "Det.model_type": ModelType.MOBILE,
                    "Det.lang_type": LangDet.CH,
                    "Cls.engine_type": EngineType.TORCH,
                    "Cls.ocr_version": OCRVersion.PPOCRV5,
                    "Cls.model_type": ModelType.MOBILE,
                    "Cls.lang_type": LangCls.CH,
                    "Rec.engine_type": EngineType.TORCH,
                    "Rec.ocr_version": OCRVersion.PPOCRV5,
                    "Rec.model_type": ModelType.MOBILE,
                    "Rec.lang_type": LangRec.CH,
                    "EngineConfig.torch.use_cuda": True,
                    "EngineConfig.torch.cuda_ep_cfg.device_id": gpu_id,
                }
            )
            return engine, "gpu"
        except Exception:
            pass
    return RapidOCR(), "cpu"


def load_base_image(path: Path, max_dim: int, autocontrast: bool) -> Image.Image:
    """Opnar biletet, gjer eventuelt autokontrast, og skalerer ned til max_dim."""
    img = Image.open(path)
    if autocontrast:
        img = ImageOps.autocontrast(img.convert("L"), cutoff=1).convert("RGB")
    else:
        img = img.convert("RGB")
    w, h = img.size
    scale = max_dim / max(w, h)
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return img


def _to_bgr(img: Image.Image) -> np.ndarray:
    return np.asarray(img)[:, :, ::-1].copy()


def _result_texts(result) -> list[str]:
    txts = getattr(result, "txts", None)
    if not txts:
        return []
    return [str(t) for t in txts]


@dataclass
class OcrOutcome:
    text: str
    rotation: Optional[int]
    raw_id: Optional[str]
    num1: Optional[str]
    num2: Optional[str]


def ocr_image(engine, path: Path, cfg: OcrConfig) -> OcrOutcome:
    """OCR-ar biletet. Prøver kvar rotasjon til ID-mønsteret blir funne."""
    base = load_base_image(path, cfg.max_dim, cfg.autocontrast)
    first_text = ""
    for rot in cfg.rotations:
        img = base.rotate(rot, expand=True) if rot else base
        result = engine(_to_bgr(img))
        text = "  ".join(_result_texts(result))
        if not first_text:
            first_text = text
        m = cfg.pattern.search(text)
        if m:
            return OcrOutcome(text=text, rotation=rot, raw_id=m.group(0), num1=m.group(1), num2=m.group(2))
    return OcrOutcome(text=first_text, rotation=None, raw_id=None, num1=None, num2=None)


@dataclass
class Classification:
    status: str
    foto_id: Optional[str]
    new_basename: Optional[str]
    year: Optional[str]
    error: str


def classify(outcome: OcrOutcome, prefix: str) -> Classification:
    """Bruker 8/9-regelen og lagar Foto-ID og nytt basisnamn."""
    if outcome.num1 is None:
        return Classification(STATUS_REVIEW_NO_ID, None, None, None, "Ingen SFFf-ID funnen i motivet")

    num1, num2 = outcome.num1, outcome.num2
    if num1[0] not in ("8", "9"):
        return Classification(
            STATUS_REVIEW_UNEXPECTED, None, None, None, f"Talet byrjar på '{num1[0]}', ikkje 8 eller 9"
        )

    transformed_num = "19" + num1
    foto_id = f"{prefix}-{transformed_num}.{num2}"
    return Classification(STATUS_OK, foto_id, foto_id, transformed_num[:4], "")


def find_matching_tiff(jpg: Path, tiff_dir: Optional[Path]) -> Optional[Path]:
    """Finn .tif/.tiff med same filstamme som jpg, i same mappe eller i tiff_dir."""
    stem = jpg.stem
    search_dirs = [jpg.parent]
    if tiff_dir and tiff_dir != jpg.parent:
        search_dirs.append(tiff_dir)
    for d in search_dirs:
        for suffix in TIFF_SUFFIXES:
            for cand in (d / (stem + suffix), d / (stem + suffix.upper())):
                if cand.exists():
                    return cand
    return None


def process_one(engine, jpg: Path, tiff_dir: Optional[Path], cfg: OcrConfig) -> dict:
    """OCR-ar éi fil og returnerer ei ferdig rapport-rad (CSV_FIELDS)."""
    try:
        outcome = ocr_image(engine, jpg, cfg)
        cls = classify(outcome, cfg.prefix)
        tiff = find_matching_tiff(jpg, tiff_dir)
        return {
            "original_jpg": str(jpg),
            "ocr_text": outcome.text[:500].replace("\n", " "),
            "rotation": "" if outcome.rotation is None else str(outcome.rotation),
            "raw_id": outcome.raw_id or "",
            "foto_id": cls.foto_id or "",
            "new_basename": cls.new_basename or "",
            "year": cls.year or "",
            "matched_tiff": str(tiff) if tiff else "",
            "status": cls.status,
            "error": cls.error,
        }
    except Exception as e:  # noqa: BLE001 - éi fil skal ikkje stoppe heile køyringa
        return {
            "original_jpg": str(jpg),
            "ocr_text": "",
            "rotation": "",
            "raw_id": "",
            "foto_id": "",
            "new_basename": "",
            "year": "",
            "matched_tiff": "",
            "status": STATUS_ERROR,
            "error": f"{type(e).__name__}: {e}",
        }


def find_jpgs(input_dir: Path) -> list[Path]:
    return sorted(p for p in input_dir.rglob("*") if p.suffix.lower() in JPG_SUFFIXES)
