#!/usr/bin/env python3
"""
Convert a card JPG to GBA-compatible tile data.

Produces (full pipeline):
  - <name>_preview.png  — quantized result at tile size, scaled up for inspection
  - <name>_tiles.h      — C arrays for palette and tile data

With --crop-only:
  - <name>_crop.png     — the raw art region crop at full source resolution,
                          so you can evaluate framing before committing to the pipeline

GBA constraints applied:
  - 4bpp mode: 16 colors per palette slot (index 0 = transparent)
  - Tile size: 8x8 pixels each
  - Palette entries are 15-bit BGR (5-5-5), stored as uint16_t
  - Tile data is packed: two 4-bit indices per byte, lo nibble first

Crop profiles
-------------
Each card type has a profile defining the art region as fractions of the full
image dimensions (top, bottom, left, right).  A centered square is then taken
from that region.  Tweak these values until --crop-only looks right before
running the full pipeline.

  top    — fraction of image height to skip from the top
  bottom — fraction of image height to keep up to (from top)
  left   — fraction of image width to skip from the left
  right  — fraction of image width to keep up to (from left)
"""

import argparse
import json
import textwrap
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

CROPS_JSON = Path(__file__).parent.parent / "gba_assets" / "custom_crops.json"


def load_custom_crops() -> dict:
    if CROPS_JSON.exists():
        return json.loads(CROPS_JSON.read_text())
    return {}


# ---------------------------------------------------------------------------
# Crop profiles — edit these to tune per card type
# ---------------------------------------------------------------------------

@dataclass
class CropProfile:
    top: float    # fraction of height — start of art region
    bottom: float # fraction of height — end of art region
    left: float   # fraction of width  — start of art region
    right: float  # fraction of width  — end of art region
    description: str = ""


CROP_PROFILES: dict[str, CropProfile] = {
    # Art fills top ~60%; name + ability text block below that. No top UI.
    "duke": CropProfile(top=0.0, bottom=0.60, left=0.0, right=1.0,
                        description="art top 60%, skip name+ability block"),

    # Cost box top-left ends ~18%; name+icon rows start ~67%.
    "starter": CropProfile(top=0.19, bottom=0.67, left=0.05, right=0.95,
                           description="skip cost box top-left, name+icons bottom"),

    # Cost box + type icon top corners end ~18%; gold cost badge bottom-left ends ~67%.
    "citizen": CropProfile(top=0.19, bottom=0.67, left=0.05, right=0.95,
                           description="skip cost+type icons top, gold badge + name bottom"),

    # Two stacked icons top-right end ~28% down and rightmost ~28% wide;
    # name+stats bar starts ~70% down. Trim right to clear icons without
    # cropping too deep into the top art.
    "monster": CropProfile(top=0.05, bottom=0.70, left=0.0, right=0.75,
                           description="skip stacked icons top-right, name+stats bottom"),

    # Two large icons top-right end ~38% down at rightmost ~33% wide;
    # art scene ends ~58% down.
    "domain": CropProfile(top=0.02, bottom=0.58, left=0.0, right=0.67,
                          description="skip large icons top-right, name+ability bottom"),
}

# Filename prefix → card type (checked against the stem, not the full path)
_PREFIX_MAP: list[tuple[str, str]] = [
    ("duke_",    "duke"),
    ("starter_", "starter"),
    ("citizen_", "citizen"),
    ("monster_", "monster"),
    ("domain_",  "domain"),
]


def detect_card_type(stem: str) -> str | None:
    for prefix, card_type in _PREFIX_MAP:
        if stem.startswith(prefix):
            return card_type
    return None


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def apply_crop_profile(img: Image.Image, profile: CropProfile) -> Image.Image:
    """Crop to the art region defined by the profile, then take a centered square."""
    w, h = img.size
    art_left   = int(w * profile.left)
    art_right  = int(w * profile.right)
    art_top    = int(h * profile.top)
    art_bottom = int(h * profile.bottom)

    art = img.crop((art_left, art_top, art_right, art_bottom))

    aw, ah = art.size
    side = min(aw, ah)
    cx = (aw - side) // 2
    cy = (ah - side) // 2
    return art.crop((cx, cy, cx + side, cy + side))


def apply_custom_crop(img: Image.Image, entry: dict) -> Image.Image:
    """Crop a fixed square centered at (cx, cy) as saved by the crop tool."""
    cx, cy, size = entry["cx"], entry["cy"], entry["size"]
    half = size // 2
    return img.crop((cx - half, cy - half, cx + half, cy + half))


def rgb_to_gba15(r: int, g: int, b: int) -> int:
    return ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)


def quantize_16color(img: Image.Image) -> Image.Image:
    """Quantize to <=15 usable colors; index 0 reserved for transparent."""
    rgb = img.convert("RGB")
    quantized = rgb.quantize(colors=15, method=Image.Quantize.MEDIANCUT, dither=1)
    palette_data = quantized.getpalette()
    pixels = list(quantized.get_flattened_data() if hasattr(quantized, "get_flattened_data") else quantized.getdata())
    new_palette = [0, 0, 0] + palette_data[: 15 * 3]
    new_pixels = [p + 1 for p in pixels]

    out = Image.new("P", quantized.size)
    out.putpalette(new_palette + [0] * (256 - 16) * 3)
    out.putdata(new_pixels)
    return out


def encode_tiles(indexed_img: Image.Image) -> list[int]:
    """Pack pixel indices into GBA 4bpp tile bytes (32 bytes per 8x8 tile)."""
    w, h = indexed_img.size
    assert w % 8 == 0 and h % 8 == 0, "Image dimensions must be multiples of 8"
    pixels = list(indexed_img.getdata())

    tile_bytes: list[int] = []
    for ty in range(h // 8):
        for tx in range(w // 8):
            for row in range(8):
                y = ty * 8 + row
                for col in range(0, 8, 2):
                    x0 = tx * 8 + col
                    lo = pixels[y * w + x0] & 0xF
                    hi = pixels[y * w + x0 + 1] & 0xF
                    tile_bytes.append(lo | (hi << 4))
    return tile_bytes


def encode_palette(indexed_img: Image.Image) -> list[int]:
    raw = indexed_img.getpalette()
    return [rgb_to_gba15(raw[i * 3], raw[i * 3 + 1], raw[i * 3 + 2]) for i in range(16)]


def write_header(out_path: Path, name: str, tile_size: int,
                 palette: list[int], tile_bytes: list[int]) -> None:
    guard = name.upper() + "_H"
    tiles_count = len(tile_bytes) // 32

    pal_body  = "\n    ".join(textwrap.wrap(", ".join(f"0x{v:04X}" for v in palette), 72))
    tile_body = "\n    ".join(textwrap.wrap(", ".join(f"0x{v:02X}" for v in tile_bytes), 72))

    out_path.write_text(f"""\
#ifndef {guard}
#define {guard}

// Auto-generated by gba_card_convert.py
// Card: {name}  |  tile size: {tile_size}x{tile_size} px  |  tiles: {tiles_count}

#include <stdint.h>

#define {name.upper()}_TILE_SIZE  {tile_size}
#define {name.upper()}_TILE_COUNT {tiles_count}
#define {name.upper()}_PAL_SIZE   16

// 15-bit BGR palette (GBA 5-5-5 format), index 0 = transparent
const uint16_t {name}_pal[{name.upper()}_PAL_SIZE] = {{
    {pal_body}
}};

// 4bpp tile data, 32 bytes per 8x8 tile (lo nibble = left pixel)
const uint8_t {name}_tiles[{len(tile_bytes)}] = {{
    {tile_body}
}};

#endif // {guard}
""")


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def run_crop_only(src: Path, profile: CropProfile, out_dir: Path) -> None:
    """Save the art-region crop at full source resolution for framing review."""
    out_dir.mkdir(parents=True, exist_ok=True)
    img = Image.open(src)
    print(f"Source: {src.name}  {img.size}")
    custom = load_custom_crops().get(src.stem)
    if custom:
        cropped = apply_custom_crop(img, custom)
        print(f"  Crop region: {cropped.size}  (custom crop)")
    else:
        cropped = apply_crop_profile(img, profile)
        print(f"  Crop region: {cropped.size}  ({profile.description})")
    out_path = out_dir / f"{src.stem}_crop.png"
    cropped.save(out_path)
    print(f"  Crop saved:  {out_path}")


def run_full(src: Path, profile: CropProfile, tile_size: int, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    name = src.stem

    img = Image.open(src)
    print(f"Source: {src.name}  {img.size} {img.mode}")

    assert tile_size % 8 == 0, "tile_size must be a multiple of 8"

    custom = load_custom_crops().get(name)
    if custom:
        img = apply_custom_crop(img, custom)
        print(f"  After crop: {img.size}  (custom crop)")
    else:
        img = apply_crop_profile(img, profile)
        print(f"  After crop: {img.size}  ({profile.description})")

    img = img.resize((tile_size, tile_size), Image.LANCZOS)
    print(f"  After resize: {img.size}")

    indexed = quantize_16color(img)
    print(f"  After quantize: {indexed.size}, mode={indexed.mode}")

    # Preview: scale up so it's actually visible
    preview_scale = max(1, 128 // tile_size)
    preview = indexed.convert("RGB").resize(
        (tile_size * preview_scale, tile_size * preview_scale), Image.NEAREST
    )
    preview_path = out_dir / f"{name}_preview.png"
    preview.save(preview_path)
    print(f"  Preview saved: {preview_path}  ({preview.size}, {preview_scale}x scale)")

    palette = encode_palette(indexed)
    tile_bytes = encode_tiles(indexed)
    print(f"  Palette entries: {len(palette)}")
    print(f"  Tile bytes: {len(tile_bytes)}  ({len(tile_bytes)//32} tiles)")

    header_path = out_dir / f"{name}_tiles.h"
    write_header(header_path, name, tile_size, palette, tile_bytes)
    print(f"  C header saved: {header_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert card JPG to GBA tile data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Known card types: {', '.join(CROP_PROFILES)}"
    )
    parser.add_argument("src", type=Path, help="Source JPG file")
    parser.add_argument("--size", type=int, default=48,
                        help="Output tile size in pixels, multiple of 8 (default: 48)")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output directory (default: gba_assets/ next to src)")
    parser.add_argument("--type", dest="card_type", default=None,
                        choices=list(CROP_PROFILES),
                        help="Card type for crop profile (auto-detected from filename if omitted)")
    parser.add_argument("--crop-only", action="store_true",
                        help="Save just the art-region crop at full resolution; skip quantize/encode")
    args = parser.parse_args()

    card_type = args.card_type or detect_card_type(args.src.stem)
    if card_type is None:
        parser.error(
            f"Cannot detect card type from '{args.src.stem}'. "
            f"Use --type to specify one of: {', '.join(CROP_PROFILES)}"
        )

    profile = CROP_PROFILES[card_type]
    print(f"Card type: {card_type}")

    out_dir = args.out or args.src.parent / "gba_assets"

    if args.crop_only:
        run_crop_only(args.src, profile, out_dir)
    else:
        run_full(args.src, profile, args.size, out_dir)


if __name__ == "__main__":
    main()
