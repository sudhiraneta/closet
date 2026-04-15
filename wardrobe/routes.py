"""
Wardrobe API Routes — FastAPI router for all wardrobe endpoints.
"""

import base64
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import Response

from config import WARDROBE_DIR
from db.postgres import db_retry

router = APIRouter(prefix="/wardrobe", tags=["wardrobe"])


@router.post("/reprocess")
def reprocess_wardrobe():
    """Re-analyze all existing wardrobe items with enriched Vision prompt and embed them."""
    from wardrobe.builder import reprocess_existing_wardrobe
    return reprocess_existing_wardrobe()


@router.get("/items")
@db_retry
def get_wardrobe_items(category: str | None = None):
    """Get wardrobe items from Postgres. Optionally filter by category."""
    from db.postgres import get_conn

    with get_conn() as conn:
        if category:
            rows = conn.execute(
                "SELECT id, category, subcategory, color, pattern, season, comfort, "
                "style_tags, suited_for, description, source_file, "
                "(image_data IS NOT NULL) as has_image "
                "FROM wardrobe WHERE category = %s ORDER BY id",
                (category,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, category, subcategory, color, pattern, season, comfort, "
                "style_tags, suited_for, description, source_file, "
                "(image_data IS NOT NULL) as has_image "
                "FROM wardrobe ORDER BY category, id",
            ).fetchall()

        counts = conn.execute(
            "SELECT category, count(*) as cnt FROM wardrobe GROUP BY category"
        ).fetchall()

    items = []
    for r in rows:
        item = dict(r)
        item["image_url"] = f"/api/wardrobe/image/{r['id']}" if r["has_image"] else None
        del item["has_image"]
        items.append(item)

    by_cat = {r["category"]: r["cnt"] for r in counts}
    return {
        "items": items,
        "summary": {"total_items": sum(by_cat.values()), "by_category": by_cat},
    }


@router.get("/image/{item_id}")
@db_retry
def get_wardrobe_image(item_id: int):
    """Serve a wardrobe item image from Postgres."""
    from db.postgres import get_conn

    with get_conn() as conn:
        row = conn.execute(
            "SELECT image_data, image_mime FROM wardrobe WHERE id = %s", (item_id,)
        ).fetchone()

    if not row or not row["image_data"]:
        return Response(status_code=404)

    return Response(content=bytes(row["image_data"]), media_type=row["image_mime"])


@router.get("/image/{item_id}/card")
@db_retry
def get_wardrobe_card_image(item_id: int):
    """Serve a processed card image — trimmed whitespace, padded to 3:4 ratio."""
    from wardrobe.image_processor import get_processed_image

    data = get_processed_image(item_id)
    if not data:
        return Response(status_code=404)

    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/outfit")
def suggest_outfit(prompt: str = "casual outfit for today"):
    """Generate outfit recommendation from a natural language prompt.

    Examples:
        "I am in NYC for my bday today suggest some party outfits"
        "casual outfit for a hike in mild weather"
        "office meeting look for rainy day in Seattle"
    """
    from wardrobe.outfit import generate_outfit
    return generate_outfit(prompt=prompt)


@router.post("/inbox")
def process_inbox():
    """Process all photos in data/wardrobe/inbox/ — auto-detect clothing and generate catalog images.

    Drop photos into data/wardrobe/inbox/, call this endpoint, and they get processed.
    Processed photos are moved to data/takeout/ so they aren't reprocessed.
    """
    from wardrobe.builder import process_inbox_photos
    result = process_inbox_photos()
    return result


@router.post("/items/add")
async def add_wardrobe_item(request: Request):
    """Manually add a clothing item via image upload."""
    from PIL import Image

    from wardrobe.vision import analyze_photo, extract_garment_image
    from wardrobe.store import load_catalog, save_catalog

    form = await request.form()
    file = form.get("file")
    if not file:
        return {"error": "No file uploaded"}

    contents = await file.read()

    img = Image.open(BytesIO(contents)).convert("RGB")
    img.thumbnail((1024, 1024), Image.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    result = analyze_photo(b64, "image/jpeg")
    if not result or not result.get("is_clothing"):
        return {"error": "Could not identify clothing in this image"}

    catalog = load_catalog()
    items_added = []

    for i, item_data in enumerate(result.get("items", [])):
        category = item_data.get("category", "tops")
        cat_map = {"top": "tops", "tops": "tops", "bottom": "bottoms", "bottoms": "bottoms",
                   "dress": "dresses", "dresses": "dresses",
                   "shoes": "shoes", "full_outfit": "tops"}
        cat_dir = cat_map.get(category, "tops")

        item_id = f"upload_{i}_{int(datetime.now(tz=timezone.utc).timestamp())}"
        output_path = WARDROBE_DIR / cat_dir / f"{item_id}.png"

        # Generate clean catalog image via Gemini
        temp_path = WARDROBE_DIR / f"_temp_{item_id}.jpg"
        img.save(temp_path, format="JPEG")
        extract_garment_image(temp_path, output_path, category=cat_dir,
                              image_b64=b64, media_type="image/jpeg")
        temp_path.unlink(missing_ok=True)

        catalog_item = {
            "id": item_id,
            "source_path": "upload",
            "image_path": str(output_path),
            "category": cat_dir,
            "subcategory": item_data.get("subcategory", ""),
            "color": item_data.get("color", ""),
            "pattern": item_data.get("pattern", "solid"),
            "description": item_data.get("description", ""),
            "season": item_data.get("season", "all_season"),
            "comfort": item_data.get("comfort", "casual"),
            "style_tags": item_data.get("style_tags", []),
            "added_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        catalog["items"].append(catalog_item)
        items_added.append(catalog_item)

    save_catalog(catalog)
    return {"items_added": len(items_added), "items": items_added}
