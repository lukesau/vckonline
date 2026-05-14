"""
Run-once script to split a citizens contact sheet into individual card JPEGs.

Grid: 10 columns x 4 rows (left-to-right, top-to-bottom), same logic as split_domains.py / split_dukes.py.

Default source: images/citizens_minus_crimson_seas.jpg
Output: images/citizens_sheet/citizen_r{row}c{col}.jpg  (1-indexed)

Game assets in images/citizens/ use names like citizen_{id:02d}_{slug}.jpg for /card-image/citizen/{id};
rename or copy from citizens_sheet/ after you match each crop to a citizen_id.
"""

from pathlib import Path
from PIL import Image

SOURCE = Path("images/citizens_minus_crimson_seas.jpg")
OUT_DIR = Path("images/citizens_sheet")
COLS = 10
ROWS = 4
TRIM = 2

OUT_DIR.mkdir(parents=True, exist_ok=True)

img = Image.open(SOURCE)
W, H = img.size
print(f"Source: {SOURCE}  {W}x{H}px  →  cell before trim: {W//COLS}x{H//ROWS}px  ({COLS}x{ROWS} grid)")

cell_w = W / COLS
cell_h = H / ROWS

for row in range(ROWS):
    for col in range(COLS):
        left = round(col * cell_w)
        top = round(row * cell_h)
        right = round((col + 1) * cell_w)
        bottom = round((row + 1) * cell_h)

        card = img.crop((left, top, right, bottom))
        card = card.crop((TRIM, TRIM, card.width - TRIM, card.height - TRIM))

        name = f"citizen_r{row+1:02d}c{col+1:02d}.jpg"
        card.save(OUT_DIR / name, quality=90)

print(f"Saved {ROWS * COLS} images to {OUT_DIR}/")
