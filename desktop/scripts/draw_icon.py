# ABOUTME: Teiknar ikon-grunnlaget (desktop/build/icon.png) som flate figurar: eit dokument med OCR-tekst.
# ABOUTME: Fargane er henta frå profilen til Vestland fylkeskommune og ligg som konstantar her.

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET = REPO_ROOT / "desktop" / "build" / "icon.png"

# Botnfargen er PMS 304 C frå profilen til Vestland fylkeskommune, #9ADBE8.
BACKGROUND = (154, 219, 232)
# Same mørkeblå som resten av grensesnittet brukar.
PAPER = (10, 50, 88)

SIZE = 1024
# Alt blir teikna i 4x og skalert ned til slutt. Det gir mjuke kantar utan eit eige
# antialias-steg, og er grunnen til at figurane kan teiknast som rette polygon.
SUPERSAMPLE = 4

# Fyrste font som finst på maskina blir brukt. Alle tre er feite nok til at "OCR" held
# seg lesbart når ikonet blir skalert ned.
BOLD_FONTS = ("seguibl.ttf", "segoeuib.ttf", "arialbd.ttf")

# Motivet i sirkelvarianten må krympe, elles stikk hjørna av dokumentet utanfor sirkelen.
CIRCLE_SCALE = 0.86


def blend(first: tuple[int, int, int], second: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    """Blandar to fargar. Brukt til bretten, som skal liggje mellom papiret og botnen."""
    return tuple(round(a + (b - a) * amount) for a, b in zip(first, second))


def load_bold_font(size: int) -> ImageFont.FreeTypeFont:
    for name in BOLD_FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    raise SystemExit(f"Fann ingen av desse feite fontane på maskina: {', '.join(BOLD_FONTS)}.")


def fitted_font(text: str, target_width: int) -> ImageFont.FreeTypeFont:
    """
    Finn den punktstorleiken som gir teksten den breidda me vil ha. Å måle og skalere er
    tryggare enn ein fast punktstorleik, for breidda varierer med kva font som finst.
    """
    probe_size = 200
    probe = load_bold_font(probe_size)
    left, _, right, _ = probe.getbbox(text)
    return load_bold_font(max(1, round(probe_size * target_width / (right - left))))


def draw_document(draw: ImageDraw.ImageDraw, size: int, scale: float) -> None:
    """Teiknar arket med brett i eine hjørnet, tekstlinjer og ordet OCR."""

    def at(fraction: float) -> int:
        """Gjer ein del av breidda om til ein piksel, målt ut frå midten så skalering held seg sentrert."""
        return round(size * (0.5 + (fraction - 0.5) * scale))

    def span(fraction: float) -> int:
        return round(size * fraction * scale)

    # Arket fyller det meste av ruta. Motivet må vere stort for å halde seg leseleg når
    # Windows viser ikonet på 16 px i oppgåvelinja og filutforskaren.
    left, right = at(0.22), at(0.78)
    top, bottom = at(0.13), at(0.87)
    radius = span(0.045)
    draw.rounded_rectangle((left, top, right, bottom), radius=radius, fill=PAPER)

    # Bretten: hjørnet blir skore bort, og halvparten som ligg att blir teikna i ein
    # mellomtone, slik at det les som eit ark med eit ombretta hjørne.
    fold = span(0.17)
    draw.polygon(
        [(left - radius, top - radius), (left + fold, top - radius), (left - radius, top + fold)],
        fill=BACKGROUND,
    )
    draw.polygon(
        [(left + fold, top), (left + fold, top + fold), (left, top + fold)],
        fill=blend(PAPER, BACKGROUND, 0.45),
    )

    # Tekstlinjer, høgrestilte som i eit skanna dokument der venstremargen varierer.
    line_right = at(0.715)
    line_height = span(0.042)
    line_gap = span(0.032)
    line_top = at(0.265)
    for width_fraction in (0.22, 0.37, 0.29, 0.37):
        line_left = line_right - span(width_fraction)
        draw.rectangle((line_left, line_top, line_right, line_top + line_height), fill=BACKGROUND)
        line_top += line_height + line_gap

    font = fitted_font("OCR", span(0.35))
    draw.text((at(0.5), at(0.695)), "OCR", font=font, fill=BACKGROUND, anchor="mm")


def build(shape: str) -> Image.Image:
    size = SIZE * SUPERSAMPLE
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if shape == "circle":
        draw.ellipse((0, 0, size - 1, size - 1), fill=BACKGROUND)
    else:
        draw.rectangle((0, 0, size - 1, size - 1), fill=BACKGROUND)
    draw_document(draw, size, CIRCLE_SCALE if shape == "circle" else 1.0)
    return image.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Teiknar ikon-grunnlaget til NB foto-namngivar")
    parser.add_argument("--out", type=Path, default=TARGET, help="Kvar PNG-en skal skrivast.")
    parser.add_argument(
        "--shape",
        choices=("square", "circle"),
        default="square",
        help="Silhuetten på botnflata. make_icons.py rundar hjørna på firkanten.",
    )
    args = parser.parse_args()

    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    build(args.shape).save(out, optimize=True)
    print(f"{out}  ({out.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
