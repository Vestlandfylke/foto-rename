# ABOUTME: Lastar ned OCR-modellane appen treng, til rapidocr sin models-mappe (eller ei valfri mappe).
# ABOUTME: Køyrast under bygging, slik at ein installert app aldri treng nettilgang for å hente modellar.
from __future__ import annotations

import argparse
from pathlib import Path

from rapidocr.inference_engine.base import FileInfo
from rapidocr.utils.download_models import download_task
from rapidocr.utils.typings import (
    EngineType,
    LangCls,
    LangDet,
    LangRec,
    ModelType,
    OCRVersion,
    TaskType,
)

# Begge oppsetta må liggje klare i ein installert app: CPU-modellane frå rapidocr sin
# standard config.yaml, og torch-modellane som nbrenamer.core.build_engine ber om når
# GPU er i bruk. GPU kan bli slått på lenge etter installasjonen, og då er det for seint
# å laste dei ned til ei programmappe som kan vere skriveverna.
MODEL_SETS: dict[str, list[FileInfo]] = {
    "CPU (onnxruntime)": [
        FileInfo(EngineType.ONNXRUNTIME, OCRVersion.PPOCRV6, TaskType.DET, LangDet.CH, ModelType.SMALL),
        FileInfo(EngineType.ONNXRUNTIME, OCRVersion.PPOCRV4, TaskType.CLS, LangCls.CH, ModelType.MOBILE),
        FileInfo(EngineType.ONNXRUNTIME, OCRVersion.PPOCRV6, TaskType.REC, LangRec.CH, ModelType.SMALL),
    ],
    "GPU (torch)": [
        FileInfo(EngineType.TORCH, OCRVersion.PPOCRV5, TaskType.DET, LangDet.CH, ModelType.MOBILE),
        FileInfo(EngineType.TORCH, OCRVersion.PPOCRV5, TaskType.CLS, LangCls.CH, ModelType.MOBILE),
        FileInfo(EngineType.TORCH, OCRVersion.PPOCRV5, TaskType.REC, LangRec.CH, ModelType.MOBILE),
    ],
}


def default_target() -> Path:
    import rapidocr

    return Path(rapidocr.__file__).resolve().parent / "models"


def main() -> None:
    parser = argparse.ArgumentParser(description="Hentar OCR-modellar for NB foto-namngivar")
    parser.add_argument(
        "--target",
        type=Path,
        default=None,
        help="Mappe modellane skal liggje i. Standard er rapidocr sin models-mappe.",
    )
    args = parser.parse_args()

    target = (args.target or default_target()).resolve()
    target.mkdir(parents=True, exist_ok=True)
    print(f"Modellmappe: {target}")

    for name, infos in MODEL_SETS.items():
        print(f"\n{name}")
        for info in infos:
            # download_task hoppar over filer som alt finst, så dette er trygt å køyre fleire gonger.
            download_task(target, info)

    files = sorted(p for p in target.iterdir() if p.is_file())
    total_mb = sum(p.stat().st_size for p in files) / 1024 / 1024
    print(f"\n{len(files)} filer, {total_mb:.0f} MB:")
    for path in files:
        print(f"  {path.name}  ({path.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
