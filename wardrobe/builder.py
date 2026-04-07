"""
Wardrobe Builder — main processing pipeline for inbox photos and reprocessing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import shutil
from datetime import datetime, timezone

from config import DATA_DIR, WARDROBE_DIR, WARDROBE_INBOX

from wardrobe.vision import image_to_base64, analyze_photo, extract_garment_image
from wardrobe.dedup import (
    perceptual_hash, is_duplicate, group_by_timestamp,
    build_semantic_text, item_exists_in_wardrobe,
)
from wardrobe.store import load_catalog, save_catalog, save_item, embed_item

TAKEOUT_DIR = DATA_DIR / "takeout"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}


def process_inbox_photos() -> dict:
    """Process all photos in ~/Downloads/wardrobe_inbox/.

    For each photo:
      1. Analyze with enriched Gemini Vision prompt (fabric, weather, style, occasion)
      2. Generate clean catalog images with Gemini image gen
      3. Save enriched item to Postgres + embed into vector store
      4. Save to catalog.json for local reference
      5. Move processed photo to data/takeout/ so it isn't reprocessed

    Drop photos here: ~/Downloads/wardrobe_inbox/
    """
    WARDROBE_INBOX.mkdir(parents=True, exist_ok=True)

    images = [
        f for f in WARDROBE_INBOX.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
    ]

    if not images:
        return {"status": "empty", "message": f"No photos in {WARDROBE_INBOX}. Drop photos there first."}

    # Skip photos already processed (by source_file in Postgres)
    from db.postgres import get_conn as _get_conn
    with _get_conn() as conn:
        existing = conn.execute("SELECT DISTINCT source_file FROM wardrobe").fetchall()
    already_done = {r["source_file"] for r in existing}
    new_images = [img for img in images if img.name not in already_done]
    skipped = len(images) - len(new_images)
    if skipped:
        print(f"  Skipping {skipped} already-processed photos")
        # Move already-processed photos out of inbox
        import shutil as _sh
        for img in images:
            if img.name in already_done:
                dest = TAKEOUT_DIR / "test_photos" / img.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    _sh.move(str(img), str(dest))
                else:
                    img.unlink()
    images = new_images

    if not images:
        return {"status": "empty", "message": f"All {skipped} photos already processed.", "skipped": skipped}

    # --- Layer 1: Burst dedup (photos taken within seconds of each other) ---
    before_burst = len(images)
    kept_images = group_by_timestamp(images)
    burst_removed = before_burst - len(kept_images)
    if burst_removed:
        # Move burst-skipped photos out of inbox
        kept_names = {img.name for img in kept_images}
        for img in images:
            if img.name not in kept_names:
                dest = TAKEOUT_DIR / "test_photos" / img.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    shutil.move(str(img), str(dest))
                else:
                    img.unlink()
        print(f"  Burst dedup: removed {burst_removed} near-simultaneous photos")
    images = kept_images

    catalog = load_catalog()
    hashes = catalog.get("hashes", {})
    stats = {
        "photos_processed": 0, "items_added": 0, "items_embedded": 0,
        "items_skipped_duplicate": 0, "errors": 0, "skipped": skipped,
        "burst_deduped": burst_removed, "hash_deduped": 0,
    }

    cat_map = {
        "top": "tops", "tops": "tops",
        "bottom": "bottoms", "bottoms": "bottoms",
        "dress": "dresses", "dresses": "dresses",
        "shoes": "shoes",
    }

    for img_path in images:
        # --- Layer 2: Perceptual hash dedup ---
        try:
            img_hash = perceptual_hash(img_path)
            dup_match = is_duplicate(img_hash, hashes)
            if dup_match:
                print(f"  SKIP hash duplicate: {img_path.name} ≈ {dup_match}")
                hashes[img_path.name] = img_hash
                stats["hash_deduped"] += 1
                # Move hash-skipped photo out of inbox
                dest = TAKEOUT_DIR / "test_photos" / img_path.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    shutil.move(str(img_path), str(dest))
                else:
                    img_path.unlink()
                continue
            hashes[img_path.name] = img_hash
        except Exception:
            pass

        print(f"  Inbox: processing {img_path.name}...")

        try:
            b64, media_type = image_to_base64(img_path)
        except Exception as e:
            print(f"    Could not load {img_path.name}: {e}")
            stats["errors"] += 1
            continue

        result = analyze_photo(b64, media_type)
        if not result or not result.get("is_clothing"):
            print(f"    No clothing found in {img_path.name}")
            stats["errors"] += 1
            continue

        stats["photos_processed"] += 1
        scene = result.get("scene") or result.get("place") or {}

        # Move source photo first so source_path points to final location
        dest = TAKEOUT_DIR / "test_photos" / img_path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(img_path), str(dest))
        source_path = str(dest)

        for i, item_data in enumerate(result.get("items", [])):
            category = item_data.get("category", "tops")
            cat_dir = cat_map.get(category, "tops")

            # --- Layer 3: Semantic dedup against existing wardrobe embeddings ---
            candidate = {**item_data, "category": cat_dir}
            existing_id = item_exists_in_wardrobe(candidate, threshold=0.15)
            if existing_id:
                print(f"    SKIP semantic duplicate: {item_data.get('color', '')} "
                      f"{item_data.get('subcategory', '')} matches existing id={existing_id}")
                stats["items_skipped_duplicate"] += 1
                continue

            item_id = f"{img_path.stem}_{i}_{int(datetime.now(tz=timezone.utc).timestamp())}"
            output_path = WARDROBE_DIR / cat_dir / f"{item_id}.png"

            # --- Process 1: Generate clean garment image ---
            # Pass specific description so Gemini extracts the RIGHT garment
            item_desc = (f"{item_data.get('color', '')} {item_data.get('subcategory', '')}. "
                         f"{item_data.get('description', '')}").strip()
            bg_removed = extract_garment_image(
                dest, output_path, category=cat_dir,
                image_b64=b64, media_type=media_type,
                item_description=item_desc,
            )

            # Read image bytes for Postgres storage
            image_bytes = None
            if bg_removed and output_path.exists():
                image_bytes = output_path.read_bytes()

            # Build enriched item dict with all new fields
            enriched_item = {
                "id": item_id,
                "source_path": source_path,
                "source_file": img_path.name,
                "image_path": str(output_path) if bg_removed else None,
                "category": cat_dir,
                "subcategory": item_data.get("subcategory", ""),
                "color": item_data.get("color", ""),
                "pattern": item_data.get("pattern", "solid"),
                "description": item_data.get("description", ""),
                "season": item_data.get("season", "all_season"),
                "comfort": item_data.get("comfort", "casual"),
                "style_tags": item_data.get("style_tags", []),
                "suited_for": item_data.get("suited_for", ""),
                "fabric": item_data.get("fabric", ""),
                "weather_suitability": item_data.get("weather_suitability", ""),
                "style_vibe": item_data.get("style_vibe", ""),
                "occasion_context": item_data.get("suited_for", ""),
                "photo_scene": scene.get("scene_description", ""),
                "place_type": scene.get("location_type", ""),
                "place_name": scene.get("landmark_or_name", ""),
                "place_activity": scene.get("activity", ""),
                "place_vibe": scene.get("vibe", ""),
                "added_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            enriched_item["semantic_text"] = build_semantic_text(enriched_item)

            # Save to catalog.json
            catalog["items"].append(enriched_item)

            # --- Process 1 done, Process 2: Save to Postgres + embed ---
            try:
                pg_id = save_item(enriched_item, image_bytes)
                print(f"    + {cat_dir}: {enriched_item['description']} → Postgres id={pg_id}")
                stats["items_added"] += 1

                chunk_id = embed_item(pg_id, enriched_item)
                if chunk_id:
                    print(f"      embedded → {chunk_id}")
                    stats["items_embedded"] += 1
            except Exception as e:
                print(f"    ERROR saving to Postgres: {e}")
                stats["items_added"] += 1  # still in catalog.json
                stats["errors"] += 1

    catalog["hashes"] = hashes
    save_catalog(catalog)
    stats["total_items"] = len(catalog["items"])
    return stats


def reprocess_existing_wardrobe() -> dict:
    """Re-analyze all existing wardrobe items with the enriched Vision prompt.

    For each item: read source_photo -> re-run Vision -> update enriched fields -> embed.
    """
    from db.postgres import get_conn

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, source_photo, category, source_file FROM wardrobe"
        ).fetchall()

    stats = {"total": len(rows), "updated": 0, "embedded": 0, "errors": 0}

    for row in rows:
        row = dict(row)
        source_path = row.get("source_photo", "")
        if not source_path or not Path(source_path).exists():
            print(f"  SKIP id={row['id']}: source photo missing at {source_path}")
            stats["errors"] += 1
            continue

        try:
            b64, media_type = image_to_base64(Path(source_path))
        except Exception as e:
            print(f"  ERROR loading {source_path}: {e}")
            stats["errors"] += 1
            continue

        result = analyze_photo(b64, media_type)
        if not result or not result.get("items"):
            print(f"  SKIP id={row['id']}: no items detected")
            stats["errors"] += 1
            continue

        # Match the correct item from the analysis by category
        cat_map = {"tops": "top", "bottoms": "bottom", "dresses": "dress", "shoes": "shoes"}
        target = cat_map.get(row["category"], row["category"])

        matched = None
        for item in result["items"]:
            if item.get("category") == target:
                matched = item
                break
        if not matched:
            matched = result["items"][0]

        scene = result.get("scene") or result.get("place") or {}

        # Build enriched dict with new + existing fields
        enriched = {
            **row,
            "fabric": matched.get("fabric", ""),
            "weather_suitability": matched.get("weather_suitability", ""),
            "style_vibe": matched.get("style_vibe", ""),
            "occasion_context": matched.get("suited_for", ""),
            "photo_scene": scene.get("scene_description", ""),
            "place_type": scene.get("location_type", ""),
            "place_name": scene.get("landmark_or_name", ""),
            "place_activity": scene.get("activity", ""),
            "place_vibe": scene.get("vibe", ""),
            "subcategory": matched.get("subcategory", ""),
            "color": matched.get("color", ""),
            "description": matched.get("description", ""),
            "season": matched.get("season", "all_season"),
            "comfort": matched.get("comfort", "casual"),
            "pattern": matched.get("pattern", "solid"),
            "style_tags": matched.get("style_tags", []),
            "suited_for": matched.get("suited_for", ""),
        }
        semantic_text = build_semantic_text(enriched)
        enriched["semantic_text"] = semantic_text

        # Update Postgres
        with get_conn() as conn:
            conn.execute(
                """UPDATE wardrobe SET
                   subcategory=%(subcategory)s, color=%(color)s, description=%(description)s,
                   pattern=%(pattern)s, season=%(season)s, comfort=%(comfort)s,
                   style_tags=%(style_tags)s, suited_for=%(suited_for)s,
                   fabric=%(fabric)s, weather_suitability=%(weather_suitability)s,
                   style_vibe=%(style_vibe)s, occasion_context=%(occasion_context)s,
                   photo_scene=%(photo_scene)s, semantic_text=%(semantic_text)s,
                   place_type=%(place_type)s, place_name=%(place_name)s,
                   place_activity=%(place_activity)s, place_vibe=%(place_vibe)s
                WHERE id=%(id)s""",
                {
                    "id": row["id"],
                    "subcategory": enriched["subcategory"],
                    "color": enriched["color"],
                    "description": enriched["description"],
                    "pattern": enriched["pattern"],
                    "season": enriched["season"],
                    "comfort": enriched["comfort"],
                    "style_tags": json.dumps(enriched["style_tags"]),
                    "suited_for": enriched["suited_for"],
                    "fabric": enriched["fabric"],
                    "weather_suitability": enriched["weather_suitability"],
                    "style_vibe": enriched["style_vibe"],
                    "occasion_context": enriched["occasion_context"],
                    "photo_scene": enriched["photo_scene"],
                    "semantic_text": semantic_text,
                    "place_type": enriched["place_type"],
                    "place_name": enriched["place_name"],
                    "place_activity": enriched["place_activity"],
                    "place_vibe": enriched["place_vibe"],
                },
            )
            conn.commit()
        stats["updated"] += 1
        print(f"  UPDATED id={row['id']}: {enriched['subcategory']} — {enriched['fabric']}")

        # Embed
        chunk_id = embed_item(row["id"], enriched)
        if chunk_id:
            stats["embedded"] += 1
            print(f"  EMBEDDED id={row['id']} → {chunk_id}")

    return stats
