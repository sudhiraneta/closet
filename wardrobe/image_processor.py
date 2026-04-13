"""
Image Processor — Trim whitespace and re-pad wardrobe images for consistent card display.

Takes raw white-background garment images (varying shapes) and produces
uniformly framed card images where every item fills ~80% of the frame.

Pipeline:
  1. Auto-crop: detect garment bounding box, trim surrounding whitespace
  2. Re-pad: add consistent margins, center in a 3:4 portrait frame
  3. Cache: store processed bytes in-memory (LRU) so it's done once per item
"""

from functools import lru_cache
from io import BytesIO

from PIL import Image, ImageFilter


def trim_whitespace(img: Image.Image, threshold: int = 240) -> Image.Image:
    """Crop away the white (or near-white) border surrounding the garment.

    Works by converting to grayscale, inverting (so garment pixels are bright),
    then using getbbox() to find the tight bounding box.
    """
    gray = img.convert("L")

    # Invert: white background → black, garment → bright
    inverted = gray.point(lambda p: 255 - p)

    # Threshold: anything below (i.e., was near-white) → 0
    binary = inverted.point(lambda p: 255 if p > (255 - threshold) else 0)

    # Small blur to ignore single-pixel noise
    binary = binary.filter(ImageFilter.MedianFilter(size=3))

    bbox = binary.getbbox()
    if not bbox:
        return img  # entirely white or can't detect — return as-is

    return img.crop(bbox)


def pad_to_ratio(
    img: Image.Image,
    target_ratio: float = 3 / 4,
    fill_pct: float = 0.80,
    bg_color: tuple = (255, 255, 255),
) -> Image.Image:
    """Center the cropped garment in a canvas with the target aspect ratio.

    Args:
        target_ratio: width / height (3:4 = 0.75 for portrait cards)
        fill_pct: how much of the canvas the garment should occupy (0.80 = 80%)
        bg_color: background color (white)
    """
    iw, ih = img.size

    # Decide canvas size so the garment fills `fill_pct` of it
    # Try fitting by height first, then check width
    canvas_h = int(ih / fill_pct)
    canvas_w = int(canvas_h * target_ratio)

    # If garment is wider than the canvas allows, fit by width instead
    if iw / fill_pct > canvas_w:
        canvas_w = int(iw / fill_pct)
        canvas_h = int(canvas_w / target_ratio)

    # Minimum output size for quality
    min_w, min_h = 400, 533  # 400x533 ≈ 3:4
    if canvas_w < min_w:
        canvas_w = min_w
        canvas_h = int(canvas_w / target_ratio)

    canvas = Image.new("RGB", (canvas_w, canvas_h), bg_color)

    # Scale garment to fit the fill area
    fill_w = int(canvas_w * fill_pct)
    fill_h = int(canvas_h * fill_pct)

    # Maintain garment aspect ratio within the fill area
    scale = min(fill_w / iw, fill_h / ih)
    new_w = int(iw * scale)
    new_h = int(ih * scale)

    resized = img.resize((new_w, new_h), Image.LANCZOS)

    # Center on canvas
    x = (canvas_w - new_w) // 2
    y = (canvas_h - new_h) // 2
    canvas.paste(resized, (x, y))

    return canvas


def process_card_image(image_bytes: bytes) -> bytes:
    """Full pipeline: raw BYTEA → trimmed + padded card image PNG bytes."""
    img = Image.open(BytesIO(image_bytes)).convert("RGB")

    trimmed = trim_whitespace(img)
    card = pad_to_ratio(trimmed)

    buf = BytesIO()
    card.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# LRU cache keyed by item_id — avoids reprocessing on every request
@lru_cache(maxsize=128)
def get_processed_image(item_id: int) -> bytes | None:
    """Fetch image from DB, process, and cache the result."""
    from db.postgres import get_conn

    with get_conn() as conn:
        row = conn.execute(
            "SELECT image_data FROM wardrobe WHERE id = %s", (item_id,)
        ).fetchone()

    if not row or not row["image_data"]:
        return None

    return process_card_image(bytes(row["image_data"]))
