"""
Run-once script to split domains_crimson_seas.jpg into individual card images.

Grid: 6 columns x 2 rows (left-to-right, top-to-bottom). The last column of each
row is a non-card slot (blank / card back) and is skipped.
Output: images/domains_crimson_seas/domain_r{row}c{col}.jpg  (1-indexed)
"""

from pathlib import Path
from PIL import Image

SOURCE = Path("images/unused/domains_crimson_seas.jpg")
OUT_DIR = Path("images/domains_crimson_seas")
COLS = 6
ROWS = 2
SKIP_LAST_COL = True  # final column of each row holds no usable card

OUT_DIR.mkdir(parents=True, exist_ok=True)

img = Image.open(SOURCE)
W, H = img.size
print(f"Source: {W}x{H}px  →  cell size: {W//COLS}x{H//ROWS}px")

cell_w = W / COLS
cell_h = H / ROWS

saved = 0
for row in range(ROWS):
    for col in range(COLS):
        if SKIP_LAST_COL and col == COLS - 1:
            continue

        left   = round(col * cell_w)
        top    = round(row * cell_h)
        right  = round((col + 1) * cell_w)
        bottom = round((row + 1) * cell_h)

        card = img.crop((left, top, right, bottom))

        name = f"domain_r{row+1:02d}c{col+1:02d}.jpg"
        card.save(OUT_DIR / name, quality=90)
        saved += 1

print(f"Saved {saved} images to {OUT_DIR}/")
