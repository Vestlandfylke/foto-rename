# ABOUTME: Kjernelogikk for NB foto-namngivar: OCR-motor (CPU/GPU), ID-lesing, 8/9-transformasjon og .tif-matching.
# ABOUTME: Delt mellom CLI-en (nb-photo-renamer.py) og web-backend (nbrenamer/webapp.py).
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageOps

# Pillow si eiga grense er slått av fordi ho er meint mot nedlasta bilete og ropar varsel på
# heilt vanlege arkivskann. I staden har me vår eiga grense under, som gir ei forståeleg melding
# og ei rad i rapporten i staden for eit varsel i ein logg ingen les.
Image.MAX_IMAGE_PIXELS = None

# Eit NB-skann er 92 til 114 megapikslar. Grensa er sett godt over det verkelege materialet, så
# ho slår ikkje inn på noko normalt. Poenget er ei fil med øydelagd hovud som hevdar absurde mål:
# utan grensa freistar Pillow å reservere minne for heile biletet, og då kan operativsystemet
# ta prosessen. Ei fil skal bli ei feilrad, ikkje ein død lesejobb.
MAX_PIXELS = 300_000_000

# Mønsteret blir køyrt mot eitt tekstfelt frå OCR-en om gongen, ikkje mot heile teksten slått
# saman. Skiljeteiknet mellom taldelen og løpenummeret kan vere punktum, komma eller bindestrek,
# for lappane er laga over mange tiår. Bindestreken og f-en i utdata lagar me sjølve, så lappen
# treng korkje «SFFf» eller punktum for å bli lesen rett.
DEFAULT_ID_PATTERN = r"SFF[Ff]?\s*[-\u2013]?\s*(\d{4,6})\s*[.,\-\u2013]\s*(\d{2,4})"

# Reglane for å binde saman to tekstfelt er ikkje konfigurerbare, for dei kviler på forma på
# SFF-lappen: taldelen står saman med «SFF», og løpenummeret er fire reine siffer. Eit felt som
# «SFFf-94263.0» blir med vilje ikkje godteke som taldel, for der har OCR-en delt løpenummeret
# midt i, og då ville me bunde det halve til noko anna.
SERIES_TAIL_PATTERN = re.compile(r"SFF[Ff]?\s*[-\u2013]?\s*(\d{4,6})\s*[.,\-\u2013]?\s*$", re.IGNORECASE)
SEQUENCE_FIELD_PATTERN = re.compile(r"^\s*(\d{4})\s*$")

# Kor nær to tekstfelt må liggje for å høyre saman, målt i tekstens eiga tjukkleik. Målt på ekte
# lappar ligg avstanden mellom taldel og løpenummer på 24 til 74 pikslar der teksten er 55 til 85
# tjukk, mens eit årstal som ikkje høyrer til ligg lenger unna eller forskjøve til sida.
NEIGHBOUR_GAP = 1.5

# Ein heil ID med minst denne tryggleiksskåren er god nok til at me sluttar å prøve fleire
# retningar. Under grensa les me vidare, for då kan ei anna retning ha eit betre bilete av
# den same lappen. Målt på ekte materiale ligg reine lappar på 0,96 og oppover.
STRONG_SCORE = 0.95

DEFAULT_ROTATIONS = "0,90,270,180"
DEFAULT_MAX_DIM = 2048
DEFAULT_PREFIX = "SFFf"
TIFF_SUFFIXES = (".tif", ".tiff")
JPG_SUFFIXES = (".jpg", ".jpeg")

STATUS_OK = "ok"
STATUS_REVIEW_NO_ID = "manuell_ingen_id"
STATUS_REVIEW_UNEXPECTED = "manuell_uventa_tal"
STATUS_ORPHAN_TIFF = "manuell_tiff_utan_jpg"
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
    STATUS_ORPHAN_TIFF: (
        "TIFF-en har ingen JPEG med same filnamn, så ingen ID kunne lesast. Fila blir "
        "aldri gissa på, men ho blir teken med slik at ho ikkje blir liggjande att."
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
    STATUS_ORPHAN_TIFF: "TIFF utan JPEG",
    STATUS_ERROR: "Feil",
}

# Mønsteret eit ferdig Foto-ID skal ha: prefiks, seks til åtte siffer, punktum og to til fire
# siffer. Med vilje mildare enn 8/9-regelen i classify(), sidan eit menneske som rettar
# manuelt kan ha grunnar maskina ikkje kjenner. Grensesnittet varslar, det sperrar ikkje.
FOTO_ID_PATTERN = rf"^{DEFAULT_PREFIX}-\d{{6,8}}\.\d{{2,4}}$"
FOTO_ID_EXAMPLE = f"{DEFAULT_PREFIX}-1994207.0007"

# `original_jpg` er kjeldefila rada handlar om. For alt som er lese med OCR er det JPEG-en,
# men ein TIFF utan JPEG-partnar får si eiga rad, og då står .tif-fila der. Namnet er behalde
# fordi det er nøkkelen både i rapporten, i gjenopptakinga og i lagringa frå steg 2.
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

# Lista over dei som gjekk gjennom, ført mens køyringa går. Rapporten fortel kva namn kvar fil
# skulle få, men ikkje kva som faktisk vart skrive, og det er det ein revisjon spør om. Kjelde og
# mål ligg side om side, slik at ein kan gå baklengs frå ei fil i ut-mappa til originalen.
DONE_LIST_FIELDS = ["original_jpg", "ny_jpg", "matched_tiff", "ny_tiff", "foto_id", "handling"]

# Rekneskapen per mappe. Med fleire hundre mapper i eit uttrekk kan ingen sjå gjennom tolv
# tusen rader, men ein kan sjå gjennom dei mappene som ikkje går opp.
FOLDER_LIST_FIELDS = [
    "mappe", "jpg", "tiff", "par", "tiff_utan_jpg", "jpg_utan_tiff", "rader", "gjer_opp", "merknad",
]

# Samanlikning av to køyringar. Kolonnane ligg parvis med a og b, slik at ein kan sjå kva dei to
# køyringane las på same fila utan å hoppe mellom to filer.
COMPARE_FIELDS = [
    "fil", "foto_id_a", "foto_id_b", "status_a", "status_b", "rotasjon_a", "rotasjon_b", "avvik",
]


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
    rotations: tuple[int, ...] = (0, 90, 270, 180)
    autocontrast: bool = True
    prefix: str = DEFAULT_PREFIX

    @classmethod
    def make(cls, pattern_str=DEFAULT_ID_PATTERN, max_dim=DEFAULT_MAX_DIM,
             rotations=DEFAULT_ROTATIONS, autocontrast=True, prefix=DEFAULT_PREFIX) -> "OcrConfig":
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


class ImageTooLarge(ValueError):
    """Biletet er så stort at me nektar å dekode det. Sjå MAX_PIXELS."""


def load_base_image(path: Path, max_dim: int, autocontrast: bool) -> Image.Image:
    """Opnar biletet, gjer eventuelt autokontrast, og skalerer ned til max_dim."""
    img = Image.open(path)
    pixels = img.size[0] * img.size[1]
    if pixels > MAX_PIXELS:
        img.close()
        raise ImageTooLarge(
            f"{img.size[0]}x{img.size[1]} = {pixels / 1e6:.0f} megapikslar, over grensa på "
            f"{MAX_PIXELS / 1e6:.0f}. Fila er truleg øydelagd. Sjekk henne manuelt."
        )
    # NB-skanna er på rundt 92 megapikslar, og me treng berre max_dim. draft() ber libjpeg
    # dekode i 1/2, 1/4 eller 1/8 med ein gong, alltid til noko som er minst max_dim, så
    # LANCZOS-skaleringa under gjer resten. Det er fire gonger raskare med same OCR-treff.
    # Kallet må skje før pikslane blir henta, og er ein nulloperasjon for andre format enn JPEG.
    img.draft("L" if autocontrast else "RGB", (max_dim, max_dim))
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


def _result_scores(result, n: int) -> list[float]:
    """OCR-en si eiga tryggleiksskår per tekstfelt. Manglar ho, reknar me alt som sikkert."""
    scores = getattr(result, "scores", None) or []
    return [float(scores[i]) if i < len(scores) else 1.0 for i in range(n)]


def _extent(box) -> tuple[float, float, float, float]:
    """Omskrivande rektangel (x0, x1, y0, y1) for eit firkanta OCR-felt."""
    xs = [float(p[0]) for p in box]
    ys = [float(p[1]) for p in box]
    return min(xs), max(xs), min(ys), max(ys)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return min(a1, b1) - max(a0, b0)


def _gap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(a0 - b1, b0 - a1, 0.0)


def _adjacent(box_a, box_b) -> bool:
    """
    Ligg dei to tekstfelta inntil kvarandre, som to delar av same lappen?

    Lappen kan stå vassrett eller loddrett i biletet sjølv etter at me har rotert, for han står
    ofte på tvers av motivet. Difor godtek me både to felt på same linje og to felt i same
    kolonne, og me krev ikkje at løpenummeret kjem etter taldelen: sett gjennom ei rotasjon kan
    det like godt liggje over. Det som avgjer er at dei flankerer kvarandre og er nær.
    """
    ax0, ax1, ay0, ay1 = _extent(box_a)
    bx0, bx1, by0, by1 = _extent(box_b)
    same_line = (
        _overlap(ay0, ay1, by0, by1) >= 0.5 * min(ay1 - ay0, by1 - by0)
        and _gap(ax0, ax1, bx0, bx1) <= NEIGHBOUR_GAP * min(ay1 - ay0, by1 - by0)
    )
    same_column = (
        _overlap(ax0, ax1, bx0, bx1) >= 0.5 * min(ax1 - ax0, bx1 - bx0)
        and _gap(ay0, ay1, by0, by1) <= NEIGHBOUR_GAP * min(ax1 - ax0, bx1 - bx0)
    )
    return same_line or same_column


@dataclass
class IdCandidate:
    num1: str
    num2: str
    raw: str
    rotation: int
    score: float
    whole: bool  # ID-en stod heil i eitt tekstfelt

    @property
    def rank(self) -> tuple[int, float]:
        """
        Ein heil ID slår alltid ein som er sett saman av to felt, uansett skår.

        Det er denne rekkjefølgja som gjer at ein lapp som blir lesen «SFF93301-0004» i éi
        retning vinn over dei same sifra lesne som «SFF93301-» pluss «7000» i ei anna: begge
        er OCR-en trygg på, men berre den eine har OCR-en sjølv sett samanhengen i.
        """
        return (1 if self.whole else 0, self.score)


def _candidates_in(result, pattern: re.Pattern, rot: int) -> list[IdCandidate]:
    """Alle ID-kandidatar i eitt OCR-resultat, både heile og slike som må settast saman."""
    txts = _result_texts(result)
    scores = _result_scores(result, len(txts))
    boxes = getattr(result, "boxes", None)
    found: list[IdCandidate] = []

    for i, text in enumerate(txts):
        m = pattern.search(text)
        if m:
            found.append(IdCandidate(m.group(1), m.group(2), m.group(0), rot, scores[i], True))

    # Utan koordinatar kan me ikkje vite kva som høyrer saman, og då gissar me ikkje.
    if boxes is None or len(boxes) < len(txts):
        return found

    sequences = [(i, m.group(1)) for i, text in enumerate(txts) if (m := SEQUENCE_FIELD_PATTERN.match(text))]
    for i, text in enumerate(txts):
        m = SERIES_TAIL_PATTERN.search(text)
        if not m:
            continue
        for j, num2 in sequences:
            if j == i or not _adjacent(boxes[i], boxes[j]):
                continue
            found.append(IdCandidate(
                m.group(1), num2, f"{text.strip()} + {txts[j].strip()}", rot, min(scores[i], scores[j]), False
            ))
    return found


@dataclass
class OcrOutcome:
    text: str
    rotation: Optional[int]
    raw_id: Optional[str]
    num1: Optional[str]
    num2: Optional[str]


def ocr_image(engine, path: Path, cfg: OcrConfig) -> OcrOutcome:
    """
    OCR-ar biletet i kvar retning og vel den beste ID-kandidaten.

    Same ID-en står ofte to stader på eit skann, handskriven i motivet og maskinskriven på ein
    lapp langs kanten, og lappen ligg gjerne på tvers. Difor les me vidare i fleire retningar i
    staden for å ta det fyrste treffet: ein lapp som står loddrett gir eit mykje betre treff når
    biletet er snudd. Ei retning som gir ein heil, trygg ID er likevel god nok, og då stoppar me,
    slik at reine lappar kostar like lite som før.
    """
    base = load_base_image(path, cfg.max_dim, cfg.autocontrast)
    first_text = ""
    best: Optional[IdCandidate] = None
    best_text = ""
    for rot in cfg.rotations:
        img = base.rotate(rot, expand=True) if rot else base
        result = engine(_to_bgr(img))
        text = "  ".join(_result_texts(result))
        if not first_text:
            first_text = text
        for cand in _candidates_in(result, cfg.pattern, rot):
            if best is None or cand.rank > best.rank:
                best, best_text = cand, text
        if best is not None and best.whole and best.score >= STRONG_SCORE:
            break
    if best is None:
        return OcrOutcome(text=first_text, rotation=None, raw_id=None, num1=None, num2=None)
    return OcrOutcome(
        text=best_text, rotation=best.rotation, raw_id=best.raw, num1=best.num1, num2=best.num2
    )


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


def process_one(engine, jpg: Path, cfg: OcrConfig, tiff: Optional[Path] = None) -> dict:
    """
    OCR-ar éi fil og returnerer ei ferdig rapport-rad (CSV_FIELDS).

    `tiff` er partnaren, eller None om JPEG-en ikkje har nokon. Paringa er gjort før me kjem
    hit, av mappe-indekseringa i folders.py, som kjenner heile mappa frå eitt katalogoppslag.
    Å slå det opp per bilete i staden ville kosta fire filsystem-oppslag for kvar fil, og det
    er ikkje gratis når materialet ligg på ein nettverksdisk.
    """
    try:
        outcome = ocr_image(engine, jpg, cfg)
        cls = classify(outcome, cfg.prefix)
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
            # Partnaren blir med sjølv om lesinga feila. Utan han ville TIFF-en blitt
            # liggjande att i kjeldemappa medan JPEG-en gjekk til _manuell.
            "matched_tiff": str(tiff) if tiff else "",
            "status": STATUS_ERROR,
            "error": f"{type(e).__name__}: {e}",
        }


def orphan_tiff_row(tiff: Path) -> dict:
    """
    Rapport-rad for ein TIFF som ikkje har nokon JPEG med same filnamn.

    Han blir aldri OCR-a: utan motivet finst det ingen ID å lese, og å gissa på eit namn
    ville vore verre enn å la mennesket ta det. Men han får ei rad, slik at han blir med i
    steg 3 og hamnar i `_manuell` med originalnamnet i staden for å bli liggjande att i
    kjeldemappa. Det siste er heile poenget når brukaren har vald å flytte.
    """
    return {
        "original_jpg": str(tiff),
        "ocr_text": "",
        "rotation": "",
        "raw_id": "",
        "foto_id": "",
        "new_basename": "",
        "year": "",
        "matched_tiff": "",
        "status": STATUS_ORPHAN_TIFF,
        "error": "",
    }


