# ABOUTME: Lagar ikonfilene til appen ut frå eitt kvadratisk PNG-grunnlag (desktop/build/icon.png).
# ABOUTME: Gjer hjørna gjennomsiktige og skriv multi-storleik .ico til installasjonsfil og web-UI.

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "desktop" / "build" / "icon.png"
WINDOW_ICON = REPO_ROOT / "desktop" / "src" / "icon.png"
INSTALLER_ICON = REPO_ROOT / "desktop" / "build" / "icon.ico"
WEB_FAVICON = REPO_ROOT / "nbrenamer" / "web" / "favicon.ico"

# Windows hentar 16-32 px til filutforskar og oppgåvelinje, 256 px til store ikon og
# installasjonsprogrammet. Alle må liggje i same .ico, elles skalerer Windows sjølv og
# resultatet blir grumsete.
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
WINDOW_ICON_SIZE = 256

# Kunsten er ein avrunda firkant på ein nesten svart flate. Alt under denne lysstyrken
# reknar me som bakgrunn som skal bort.
DARK_LEVEL = 40
# Maska blir teikna i 4x og skalert ned, som gir mjuke kantar utan eit eige antialias-steg.
SUPERSAMPLE = 4


def corner_radius(image: Image.Image) -> int:
    """
    Finn radiusen til den avrunda firkanten ved å måle kor langt inn den mørke flata går
    langs øvre kant. For ein avrunda firkant sluttar det mørke feltet der kurva møter kanten.
    """
    pixels = image.load()
    width = image.width
    extent = 0
    while extent < width:
        red, green, blue, _ = pixels[extent, 0]
        if max(red, green, blue) >= DARK_LEVEL:
            break
        extent += 1
    # Litt monaleg på toppen, slik at antialias-pikslane mellom svart og blått òg blir borte.
    return min(extent + 6, width // 2)


def zoomed(image: Image.Image, fraction: float) -> Image.Image:
    """
    Skjer bort like mykje av den tomme flata på alle fire sidene og strekk resten ut igjen.
    Motivet fyller då meir av ruta, som er heile forskjellen på om eit ikon er leseleg på
    16 px eller ikkje. Bakgrunnen er einsfarga, så snittet blir usynleg.
    """
    if fraction <= 0:
        return image
    inset = round(image.width * fraction)
    box = (inset, inset, image.width - inset, image.height - inset)
    print(f"Zoomar inn {fraction:.0%} på kvar side")
    return image.crop(box).resize(image.size, Image.LANCZOS)


def rounded(image: Image.Image, min_fraction: float) -> Image.Image:
    """
    Rundar hjørna. Radiusen må vere minst like stor som avrundinga i grunnlaget, elles blir
    mørke restpikslar ståande i hjørna. Etter ein zoom er avrundinga skoren bort, og då er
    det `min_fraction` som gir tilbake fasongen.
    """
    radius = max(corner_radius(image), round(image.width * min_fraction))
    size = (image.width * SUPERSAMPLE, image.height * SUPERSAMPLE)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size[0] - 1, size[1] - 1), radius=radius * SUPERSAMPLE, fill=255
    )
    result = image.copy()
    result.putalpha(mask.resize(image.size, Image.LANCZOS))
    print(f"Runda hjørne med radius {radius} px")
    return result


def write_preview(image: Image.Image, path: Path) -> None:
    """Legg dei små storleikane side om side på lys og mørk botn, for augesjekk."""
    sizes = [16, 24, 32, 48, 64]
    cell, gap = 128, 12
    width = len(sizes) * cell + (len(sizes) + 1) * gap
    canvas = Image.new("RGB", (width, 2 * cell + 3 * gap), "#eef2f7")
    ImageDraw.Draw(canvas).rectangle((0, cell + 2 * gap, width, canvas.height), fill="#0A3258")
    for row, top in enumerate((gap, cell + 3 * gap)):
        for column, size in enumerate(sizes):
            small = image.resize((size, size), Image.LANCZOS)
            zoomed = small.resize((cell, cell), Image.NEAREST)
            canvas.paste(zoomed, (gap + column * (cell + gap), top), zoomed)
    canvas.save(path)
    print(f"Førehandsvising: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Lagar ikonfilene til NB foto-namngivar")
    parser.add_argument("--source", type=Path, default=SOURCE, help="Kvadratisk PNG-grunnlag.")
    parser.add_argument("--preview", type=Path, default=None, help="Skriv ei førehandsvising hit.")
    parser.add_argument(
        "--zoom",
        type=float,
        default=0.0,
        help="Del av kvar side som blir skoren bort før ikonet blir laga, t.d. 0.08.",
    )
    parser.add_argument(
        "--radius",
        type=float,
        default=0.10,
        help="Minste hjørneradius, som del av breidda.",
    )
    args = parser.parse_args()

    source = Image.open(args.source).convert("RGBA")
    if source.width != source.height:
        raise SystemExit(f"Grunnlaget må vere kvadratisk, ikkje {source.width}x{source.height}.")

    icon = rounded(zoomed(source, args.zoom), args.radius)
    # Grunnlaget blir aldri skrive over, slik at skriptet kan køyrast om att utan at zoomen
    # blir lagd oppå seg sjølv gong etter gong.
    icon.resize((WINDOW_ICON_SIZE, WINDOW_ICON_SIZE), Image.LANCZOS).save(WINDOW_ICON, optimize=True)
    for target in (INSTALLER_ICON, WEB_FAVICON):
        icon.save(target, format="ICO", sizes=ICO_SIZES)

    if args.preview:
        write_preview(icon, args.preview)

    for path in (WINDOW_ICON, INSTALLER_ICON, WEB_FAVICON):
        print(f"{path.relative_to(REPO_ROOT)}  ({path.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
