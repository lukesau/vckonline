"""
Run-once script to split nobles.jpg into individual card JPEGs.

Same cell-from-grid logic as split_dukes.py / split_citizens_sheet.py, but no
post-crop trimming (nobles cards are smaller and trimming eats real artwork).

Grid: 5 columns x 4 rows (left-to-right, top-to-bottom).
  - Column 5 of rows 1-3 is blank and is skipped.
  - Column 5 of row 4 is the nobles card back.
  - The remaining 16 cells are the noble cards.

Output: images/nobles_sheet/noble_r{row}c{col}.jpg (1-indexed), plus
        images/nobles_sheet/noble_back.jpg for the card back.

Each crop is fit to TARGET, whose aspect matches the Amarynth Noble slot on
the crimson seas mat (520x814, aspect ~0.639; see SAIL_LAYOUT.nobles in
static/game/src/02-render-and-board.js). The source cells are slightly wider
than the slot, so we center-crop to the slot aspect (a small horizontal trim,
no distortion) and then resize down.

TARGET is the slot aspect scaled to ~70-75% of the canonical 400x571 card
(width 280 = 0.70*400, height 438 ~= 0.77*571). The downscale also averages
out the dot-matrix/halftone artifacts from the scan.
"""

from pathlib import Path
from PIL import Image

SOURCE = Path("images/unused/nobles.jpg")
OUT_DIR = Path("images/nobles_sheet")
COLS = 5
ROWS = 4
TARGET = (280, 438)


def fit_to_aspect(card, target):
    """Center-crop card to target's aspect ratio, then resize to target."""
    tw, th = target
    cw, ch = card.size
    target_aspect = tw / th
    src_aspect = cw / ch
    if src_aspect > target_aspect:
        new_w = round(ch * target_aspect)
        left = (cw - new_w) // 2
        card = card.crop((left, 0, left + new_w, ch))
    elif src_aspect < target_aspect:
        new_h = round(cw / target_aspect)
        top = (ch - new_h) // 2
        card = card.crop((0, top, cw, top + new_h))
    return card.resize(target, Image.LANCZOS)

OUT_DIR.mkdir(parents=True, exist_ok=True)

img = Image.open(SOURCE)
W, H = img.size
cell_w = W / COLS
cell_h = H / ROWS
print(f"Source: {SOURCE}  {W}x{H}px  →  cell {cell_w:.1f}x{cell_h:.1f}px  ({COLS}x{ROWS} grid)  →  resize {TARGET[0]}x{TARGET[1]}px")

saved = 0
for row in range(ROWS):
    for col in range(COLS):
        is_back = row == ROWS - 1 and col == COLS - 1
        is_blank = col == COLS - 1 and not is_back
        if is_blank:
            continue

        left = round(col * cell_w)
        top = round(row * cell_h)
        right = round((col + 1) * cell_w)
        bottom = round((row + 1) * cell_h)

        card = img.crop((left, top, right, bottom))
        card = fit_to_aspect(card, TARGET)

        name = "noble_back.jpg" if is_back else f"noble_r{row+1:02d}c{col+1:02d}.jpg"
        card.save(OUT_DIR / name, quality=90)
        saved += 1

print(f"Saved {saved} images to {OUT_DIR}/")
