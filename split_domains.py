"""
Run-once script to split domains.jpg into individual card images.

Grid: 7 columns x 10 rows (left-to-right, top-to-bottom)
Output: images/domains/domain_r{row}c{col}.jpg  (1-indexed)
"""

from pathlib import Path
from PIL import Image

SOURCE = Path("images/domains.jpg")
OUT_DIR = Path("images/domains")
COLS = 10
ROWS = 7
TRIM = 2  # pixels to shave from each edge after splitting

OUT_DIR.mkdir(parents=True, exist_ok=True)

img = Image.open(SOURCE)
W, H = img.size
print(f"Source: {W}x{H}px  →  cell size before trim: {W//COLS}x{H//ROWS}px")

cell_w = W / COLS
cell_h = H / ROWS

for row in range(ROWS):
    for col in range(COLS):
        left   = round(col * cell_w)
        top    = round(row * cell_h)
        right  = round((col + 1) * cell_w)
        bottom = round((row + 1) * cell_h)

        card = img.crop((left, top, right, bottom))
        card = card.crop((TRIM, TRIM, card.width - TRIM, card.height - TRIM))

        name = f"domain_r{row+1:02d}c{col+1:02d}.jpg"
        card.save(OUT_DIR / name, quality=90)

print(f"Saved {ROWS * COLS} images to {OUT_DIR}/")
