"""
Run-once script to split monster and warden contact sheets into individual JPEGs.

Same crop math as split_domains.py / split_citizens_sheet.py (uniform grid, TRIM px per edge).

For monsters.jpg, the last row has solid-black placeholder cells; those are skipped when they look
like uniform black (low mean and low stddev on luminance after trim).

Outputs (do not overwrite images/monsters/ game assets until you match IDs and rename):
  images/monsters_sheet/monster_r{row}c{col}.jpg
  images/wardens_sheet/warden_r{row}c{col}.jpg

Game lookup uses monster_{id:02d}_*.jpg under images/monsters/ for /card-image/monster/{id}.
"""

from pathlib import Path
from PIL import Image
from PIL import ImageStat

TRIM = 2

# (source_path, out_dir, cols, rows, skip_uniform_black)
SOURCES = [
    ("images/monsters.jpg", "images/monsters_sheet", 10, 6, True),
    ("images/wardens.jpg", "images/wardens_sheet", 10, 2, False),
]


def _looks_like_blank_slot(card):
    """True for empty black grid cells; false for normal card art."""
    stat = ImageStat.Stat(card.convert("L"))
    mean = stat.mean[0]
    std = stat.stddev[0]
    return mean < 18 and std < 14


for source_path, out_dir_path, cols, rows, skip_blank in SOURCES:
    source = Path(source_path)
    out_dir = Path(out_dir_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    img = Image.open(source)
    W, H = img.size
    cell_w = W / cols
    cell_h = H / rows
    stem = source.stem
    print(f"{source.name}: {W}x{H}px  →  cell ~{W//cols}x{H//rows}px  ({cols}x{rows} grid)")

    saved = 0
    skipped = 0
    prefix = "monster" if stem == "monsters" else "warden"

    for row in range(rows):
        for col in range(cols):
            left = round(col * cell_w)
            top = round(row * cell_h)
            right = round((col + 1) * cell_w)
            bottom = round((row + 1) * cell_h)

            card = img.crop((left, top, right, bottom))
            card = card.crop((TRIM, TRIM, card.width - TRIM, card.height - TRIM))

            if skip_blank and _looks_like_blank_slot(card):
                skipped += 1
                continue

            name = f"{prefix}_r{row+1:02d}c{col+1:02d}.jpg"
            card.save(out_dir / name, quality=90)
            saved += 1

    extra = f", skipped {skipped} blank cells" if skipped else ""
    print(f"  → saved {saved} images to {out_dir}/{extra}")
