"""
Run-once script to split agents.jpg and relics.jpg into individual card images.

Both sheets are a 10-column x 2-row grid of ~400x571 cells. The cell size is
derived from the image dimensions / grid starting at the top-left corner, and we
do NOT trim any pixels (the source cards are already at card resolution).

Layout per sheet:
  - Row 1: columns 1-10 are all cards.
  - Row 2: the last column (col 10) is the card back; some leading columns are
    cards and the rest are blank and skipped.

Output: images/<kind>/<kind>_<id>_<slug>.jpg, where <id> is the card's DB id
(see sql/insert_all_agents.sql / sql/insert_all_relics.sql) zero-padded to two
digits so the `/card-image/{type}/{id}` endpoint resolves it. Plus
images/<kind>/<kind>_back.jpg for the card back.
"""

from pathlib import Path
from PIL import Image

SHEETS = [
    {
        "source": "images/unused/agents.jpg",
        "out_dir": "images/agents",
        "prefix": "agent",
        # row 2: columns 1-5 are cards, 6-9 blank, 10 is the card back
        "row2_cards": 5,
        # (row, col) -> (db_id, slug). Grid order is left-to-right/top-to-bottom;
        # db_id is the alphabetical id from sql/insert_all_agents.sql.
        "names": {
            (1, 1): (9, "kings_herald"), (1, 2): (10, "prefect"), (1, 3): (11, "publican"),
            (1, 4): (12, "sapper"), (1, 5): (13, "squire"), (1, 6): (14, "town_crier"),
            (1, 7): (15, "treasurer"), (1, 8): (1, "abbot"), (1, 9): (2, "assassin"),
            (1, 10): (3, "baron"),
            (2, 1): (4, "bishop"), (2, 2): (5, "brute_squad"), (2, 3): (6, "captain"),
            (2, 4): (7, "green_witch"), (2, 5): (8, "huntress"),
        },
    },
    {
        "source": "images/unused/relics.jpg",
        "out_dir": "images/relics",
        "prefix": "relic",
        # row 2: columns 1-3 are cards, 4-9 blank, 10 is the card back
        "row2_cards": 3,
        # (row, col) -> (db_id, slug); db_id from sql/insert_all_relics.sql.
        "names": {
            (1, 1): (1, "cornelius_ring"), (1, 2): (2, "dragon_orb"), (1, 3): (3, "evermap"),
            (1, 4): (4, "fire_lance"), (1, 5): (5, "gold_bastion"), (1, 6): (6, "lich_sword"),
            (1, 7): (7, "mask_of_asteraten"), (1, 8): (8, "philosophers_tome"),
            (1, 9): (9, "st_aquilas_statue"), (1, 10): (10, "staff_of_urdr"),
            (2, 1): (11, "thunder_axe"), (2, 2): (12, "treant_chest"), (2, 3): (13, "violet_ring"),
        },
    },
]

COLS = 10
ROWS = 2

for sheet in SHEETS:
    source = Path(sheet["source"])
    out_dir = Path(sheet["out_dir"])
    prefix = sheet["prefix"]
    row2_cards = sheet["row2_cards"]
    names = sheet["names"]
    out_dir.mkdir(parents=True, exist_ok=True)

    img = Image.open(source)
    W, H = img.size
    cell_w = W / COLS
    cell_h = H / ROWS
    print(f"{source.name}: {W}x{H}px  →  cell {cell_w:.1f}x{cell_h:.1f}px  ({COLS}x{ROWS} grid)")

    saved = 0
    for row in range(ROWS):
        for col in range(COLS):
            is_back = row == 1 and col == COLS - 1
            is_blank = row == 1 and not is_back and col >= row2_cards
            if is_blank:
                continue

            left = round(col * cell_w)
            top = round(row * cell_h)
            right = round((col + 1) * cell_w)
            bottom = round((row + 1) * cell_h)

            card = img.crop((left, top, right, bottom))

            if is_back:
                name = f"{prefix}_back.jpg"
            else:
                card_id, slug = names[(row + 1, col + 1)]
                name = f"{prefix}_{card_id:02d}_{slug}.jpg"
            card.save(out_dir / name, quality=95)
            saved += 1

    print(f"  → saved {saved} images to {out_dir}/")
