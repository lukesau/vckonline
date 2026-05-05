"""
Normalize arbitrary card artwork to the standard game card pixel size (400x570).

If the source aspect ratio differs from the target, the image is center-cropped
to match before resizing so nothing is stretched or squashed.
"""

from io import BytesIO
from pathlib import Path

from PIL import Image

CARD_IMAGE_WIDTH = 400
CARD_IMAGE_HEIGHT = 570


def _cover_crop_to_aspect(img, target_w, target_h):
    w, h = img.size
    target_ratio = target_w / target_h
    src_ratio = w / h
    if src_ratio > target_ratio:
        new_w = max(1, int(round(h * target_ratio)))
        x0 = (w - new_w) // 2
        return img.crop((x0, 0, x0 + new_w, h))
    if src_ratio < target_ratio:
        new_h = max(1, int(round(w / target_ratio)))
        y0 = (h - new_h) // 2
        return img.crop((0, y0, w, y0 + new_h))
    return img


def normalize_card_image(source):
    """
    Load a card image from path, Path, or file-like, crop to 400:570 if needed,
    resize to CARD_IMAGE_WIDTH x CARD_IMAGE_HEIGHT, return RGB PIL Image.
    """
    img = Image.open(source)
    img = img.convert("RGB")
    img = _cover_crop_to_aspect(img, CARD_IMAGE_WIDTH, CARD_IMAGE_HEIGHT)
    img = img.resize(
        (CARD_IMAGE_WIDTH, CARD_IMAGE_HEIGHT),
        Image.Resampling.LANCZOS,
    )
    return img


def card_image_to_jpeg_bytes(source, quality=90):
    """Normalize source image and return JPEG bytes (for HTTP responses, caches, etc.)."""
    img = normalize_card_image(source)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def write_normalized_card_jpeg(source, dest_path, quality=90):
    """
    Normalize source and write a JPEG to dest_path.
    Useful for one-off asset prep or batch scripts.
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    img = normalize_card_image(source)
    img.save(str(dest_path), format="JPEG", quality=quality, optimize=True)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        sys.stderr.write(
            "Usage: python card_image_utils.py <source_image> <dest_jpeg>\n"
            "       Output is center-cropped to 400:570 if needed, then resized.\n"
        )
        sys.exit(2)
    write_normalized_card_jpeg(sys.argv[1], sys.argv[2])
    print(sys.argv[2])
