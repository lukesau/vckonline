#!/usr/bin/env python3
"""
Interactive crop placement tool for GBA card art.

For each card image, shows the artwork with a movable crop square overlaid.
Confirmed positions are saved to gba_assets/custom_crops.json and picked up
automatically by gba_card_convert.py.

Controls
--------
  Mouse drag    — move the crop square
  Arrow keys    — nudge 1px on the source image
  Shift+Arrow   — nudge 10px on the source image
  Enter / Space — confirm and advance to next card
  S             — skip (keep existing or profile-default crop)
  Q / Escape    — quit and save progress

Usage
-----
  python3 scripts/gba_crop_tool.py                   # all card types
  python3 scripts/gba_crop_tool.py --type monster    # one type only
  python3 scripts/gba_crop_tool.py --size 160        # crop square px on source
  python3 scripts/gba_crop_tool.py --redo            # revisit already-cropped cards
"""

import argparse
import json
import tkinter as tk
import tkinter.messagebox
from pathlib import Path

from PIL import Image, ImageTk, ImageDraw

# ---------------------------------------------------------------------------
# Import crop profiles from the conversion script
# ---------------------------------------------------------------------------
import sys
sys.path.insert(0, str(Path(__file__).parent))
from gba_card_convert import CROP_PROFILES, detect_card_type

CROPS_JSON = Path(__file__).parent.parent / "gba_assets" / "custom_crops.json"

CARD_GLOBS = {
    "duke":    ["images/dukes/duke_*.jpg"],
    "starter": ["images/starters/starter_*.jpg", "images/starters/starter_*.jpeg"],
    "citizen": ["images/citizens/citizen_*.jpg"],
    "monster": ["images/monsters/monster_*.jpg"],
    "domain":  ["images/domains/domain_*.jpg"],
}

# Max display size (the image is scaled to fit, crop square is scaled with it)
DISPLAY_MAX = 700


def collect_images(root: Path, types: list[str]) -> list[Path]:
    paths = []
    for t in types:
        for glob in CARD_GLOBS.get(t, []):
            paths.extend(sorted(root.glob(glob)))
    return paths


def load_crops() -> dict:
    if CROPS_JSON.exists():
        return json.loads(CROPS_JSON.read_text())
    return {}


def save_crops(crops: dict) -> None:
    CROPS_JSON.parent.mkdir(parents=True, exist_ok=True)
    CROPS_JSON.write_text(json.dumps(crops, indent=2))


def profile_default_center(img_w: int, img_h: int, profile, crop_size: int) -> tuple[int, int]:
    """Center of the profile's art region, clamped so the crop square fits inside it."""
    art_left   = int(img_w * profile.left)
    art_right  = int(img_w * profile.right)
    art_top    = int(img_h * profile.top)
    art_bottom = int(img_h * profile.bottom)
    cx = (art_left + art_right) // 2
    cy = (art_top + art_bottom) // 2
    half = crop_size // 2
    cx = max(art_left + half, min(art_right  - half, cx))
    cy = max(art_top  + half, min(art_bottom - half, cy))
    return cx, cy


class CropTool:
    def __init__(self, root_tk: tk.Tk, images: list[Path],
                 crops: dict, crop_size: int, project_root: Path):
        self.root_tk = root_tk
        self.images = images
        self.crops = crops
        self.crop_size = crop_size
        self.project_root = project_root

        self.idx = 0
        self.scale = 1.0          # source-px → display-px
        self.src_cx = 0           # crop center in source pixels
        self.src_cy = 0
        self.drag_start = None    # (mouse_x, mouse_y, src_cx, src_cy) at drag begin
        self.img_w = 0
        self.img_h = 0
        self.card_type = ""
        self.profile = None

        root_tk.title("GBA Crop Tool")
        root_tk.resizable(False, False)

        self.canvas = tk.Canvas(root_tk, cursor="fleur")
        self.canvas.pack()

        status_frame = tk.Frame(root_tk)
        status_frame.pack(fill=tk.X, padx=8, pady=4)

        self.status_var = tk.StringVar()
        tk.Label(status_frame, textvariable=self.status_var, anchor="w").pack(side=tk.LEFT)

        btn_frame = tk.Frame(root_tk)
        btn_frame.pack(pady=(0, 6))
        tk.Button(btn_frame, text="Skip (S)", width=10, command=self.skip).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_frame, text="Confirm (↵)", width=12, command=self.confirm).pack(side=tk.LEFT, padx=4)

        root_tk.bind("<Return>",       lambda e: self.confirm())
        root_tk.bind("<space>",        lambda e: self.confirm())
        root_tk.bind("s",              lambda e: self.skip())
        root_tk.bind("S",              lambda e: self.skip())
        root_tk.bind("<Escape>",       lambda e: self.quit())
        root_tk.bind("q",              lambda e: self.quit())
        root_tk.bind("Q",              lambda e: self.quit())
        root_tk.bind("<Left>",         lambda e: self.nudge(-1, 0))
        root_tk.bind("<Right>",        lambda e: self.nudge( 1, 0))
        root_tk.bind("<Up>",           lambda e: self.nudge( 0,-1))
        root_tk.bind("<Down>",         lambda e: self.nudge( 0, 1))
        root_tk.bind("<Shift-Left>",   lambda e: self.nudge(-10, 0))
        root_tk.bind("<Shift-Right>",  lambda e: self.nudge( 10, 0))
        root_tk.bind("<Shift-Up>",     lambda e: self.nudge( 0,-10))
        root_tk.bind("<Shift-Down>",   lambda e: self.nudge( 0, 10))
        self.canvas.bind("<ButtonPress-1>",   self.on_mouse_down)
        self.canvas.bind("<B1-Motion>",       self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)

        self.load_card()

    # ------------------------------------------------------------------

    def load_card(self):
        if self.idx >= len(self.images):
            self.finish()
            return

        path = self.images[self.idx]
        stem = path.stem
        self.card_type = detect_card_type(stem) or "unknown"
        self.profile   = CROP_PROFILES.get(self.card_type)

        src = Image.open(path).convert("RGB")
        self.img_w, self.img_h = src.size

        # Scale to fit DISPLAY_MAX
        self.scale = min(DISPLAY_MAX / self.img_w, DISPLAY_MAX / self.img_h)
        disp_w = int(self.img_w * self.scale)
        disp_h = int(self.img_h * self.scale)

        # Restore saved position or use profile default
        if stem in self.crops:
            entry = self.crops[stem]
            self.src_cx = entry["cx"]
            self.src_cy = entry["cy"]
        elif self.profile:
            self.src_cx, self.src_cy = profile_default_center(
                self.img_w, self.img_h, self.profile, self.crop_size)
        else:
            self.src_cx = self.img_w // 2
            self.src_cy = self.img_h // 2

        self.canvas.config(width=disp_w, height=disp_h)
        self._src = src          # keep reference
        self._disp_img = src.resize((disp_w, disp_h), Image.LANCZOS)
        self._redraw()

        remaining = len(self.images) - self.idx
        saved_mark = " ✓" if stem in self.crops else ""
        self.status_var.set(
            f"[{self.idx+1}/{len(self.images)}]  {path.name}  ({self.card_type}){saved_mark}"
        )

    def _redraw(self):
        disp_w, disp_h = self._disp_img.size
        overlay = self._disp_img.copy()
        draw = ImageDraw.Draw(overlay, "RGBA")

        # Dim everything outside the crop square
        half_d = int(self.crop_size * self.scale / 2)
        cx_d   = int(self.src_cx * self.scale)
        cy_d   = int(self.src_cy * self.scale)

        # Four dim rectangles surrounding the crop square
        dim = (0, 0, 0, 140)
        if cy_d - half_d > 0:
            draw.rectangle([0, 0, disp_w, cy_d - half_d], fill=dim)
        if cy_d + half_d < disp_h:
            draw.rectangle([0, cy_d + half_d, disp_w, disp_h], fill=dim)
        if cx_d - half_d > 0:
            draw.rectangle([0, cy_d - half_d, cx_d - half_d, cy_d + half_d], fill=dim)
        if cx_d + half_d < disp_w:
            draw.rectangle([cx_d + half_d, cy_d - half_d, disp_w, cy_d + half_d], fill=dim)

        # Crop square border
        draw.rectangle(
            [cx_d - half_d, cy_d - half_d, cx_d + half_d, cy_d + half_d],
            outline=(255, 220, 0, 255), width=2
        )

        # Profile safe-zone border (faint)
        if self.profile:
            pl = int(self.img_w * self.profile.left  * self.scale)
            pr = int(self.img_w * self.profile.right * self.scale)
            pt = int(self.img_h * self.profile.top   * self.scale)
            pb = int(self.img_h * self.profile.bottom* self.scale)
            draw.rectangle([pl, pt, pr, pb], outline=(100, 200, 255, 160), width=1)

        self._tk_img = ImageTk.PhotoImage(overlay)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._tk_img)

    def _clamp(self):
        half = self.crop_size // 2
        self.src_cx = max(half, min(self.img_w - half, self.src_cx))
        self.src_cy = max(half, min(self.img_h - half, self.src_cy))

    def nudge(self, dx: int, dy: int):
        self.src_cx += dx
        self.src_cy += dy
        self._clamp()
        self._redraw()

    def on_mouse_down(self, event):
        self.drag_start = (event.x, event.y, self.src_cx, self.src_cy)

    def on_mouse_drag(self, event):
        if self.drag_start is None:
            return
        mx0, my0, cx0, cy0 = self.drag_start
        dx = int((event.x - mx0) / self.scale)
        dy = int((event.y - my0) / self.scale)
        self.src_cx = cx0 + dx
        self.src_cy = cy0 + dy
        self._clamp()
        self._redraw()

    def on_mouse_up(self, event):
        self.drag_start = None

    def confirm(self):
        stem = self.images[self.idx].stem
        self.crops[stem] = {"cx": self.src_cx, "cy": self.src_cy, "size": self.crop_size}
        save_crops(self.crops)
        self.idx += 1
        self.load_card()

    def skip(self):
        self.idx += 1
        self.load_card()

    def quit(self):
        save_crops(self.crops)
        self.root_tk.destroy()

    def finish(self):
        save_crops(self.crops)
        self.status_var.set("All done! Crops saved.")
        tk.messagebox.showinfo("Done", f"All cards processed.\nCrops saved to {CROPS_JSON}")
        self.root_tk.destroy()


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Interactive GBA card crop placement tool")
    parser.add_argument("--type", dest="card_type", default=None,
                        choices=list(CROP_PROFILES),
                        help="Only process this card type (default: all)")
    parser.add_argument("--size", type=int, default=180,
                        help="Crop square size in source pixels (default: 180)")
    parser.add_argument("--redo", action="store_true",
                        help="Include cards that already have a saved crop")
    parser.add_argument("--range", dest="range_", default=None, metavar="START:END",
                        help="1-based slice of the image list, e.g. 1:10 or 1-10 (END is inclusive)")
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent
    types = [args.card_type] if args.card_type else list(CROP_PROFILES)
    images = collect_images(project_root, types)

    crops = load_crops()

    if args.range_:
        sep = ":" if ":" in args.range_ else "-"
        parts = args.range_.split(sep, 1)
        start, end = int(parts[0]) - 1, int(parts[1])  # convert to 0-based, end inclusive
        images = images[start:end]

    if not args.redo:
        already_done = set(crops)
        images = [p for p in images if p.stem not in already_done]

    if not images:
        print("Nothing to crop. Use --redo to revisit saved crops.")
        return

    print(f"{len(images)} cards to crop  (square size: {args.size}px on source)")

    root_tk = tk.Tk()
    app = CropTool(root_tk, images, crops, args.size, project_root)
    root_tk.mainloop()


if __name__ == "__main__":
    main()
