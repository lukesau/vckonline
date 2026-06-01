"""
Run-once script to split dukes.jpg and dukes_expansion.jpg into individual card images.
Card cell size is derived from image dimensions / grid, starting from the top-left corner.
"""

from pathlib import Path
from PIL import Image

TRIM = 2

SOURCES = [
    ("images/dukes.jpg",           "images/dukes", 10, 3),
    ("images/dukes_expansion.jpg", "images/dukes", 4,  2),
]

for source_path, out_dir_path, cols, rows in SOURCES:
    source  = Path(source_path)
    out_dir = Path(out_dir_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    img = Image.open(source)
    W, H = img.size
    cell_w = W / cols
    cell_h = H / rows
    print(f"{source.name}: {W}x{H}px  →  cell {cell_w:.1f}x{cell_h:.1f}px  ({cols}x{rows} grid)")

    for row in range(rows):
        for col in range(cols):
            left   = round(col * cell_w)
            top    = round(row * cell_h)
            right  = round((col + 1) * cell_w)
            bottom = round((row + 1) * cell_h)

            card = img.crop((left, top, right, bottom))
            card = card.crop((TRIM, TRIM, card.width - TRIM, card.height - TRIM))

            name = f"duke_r{row+1:02d}c{col+1:02d}.jpg"
            out_path = out_dir / name
            if out_path.exists():
                stem, suffix = name.rsplit(".", 1)
                name = f"{stem}_exp.{suffix}"
            card.save(out_dir / name, quality=90)

    print(f"  → saved to {out_dir}/")
