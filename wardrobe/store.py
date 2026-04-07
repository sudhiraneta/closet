"""
Wardrobe Store — Postgres persistence and vector embedding for wardrobe items.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import json

from config import WARDROBE_DIR

from wardrobe.dedup import build_semantic_text

CATALOG_FILE = WARDROBE_DIR / "catalog.json"


def load_catalog() -> dict:
    """Load the wardrobe catalog from disk."""
    if CATALOG_FILE.exists():
        return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    return {"items": [], "last_scan": None, "hashes": {}, "skipped": []}


def save_catalog(catalog: dict) -> None:
    """Save the wardrobe catalog to disk."""
    WARDROBE_DIR.mkdir(parents=True, exist_ok=True)
    CATALOG_FILE.write_text(json.dumps(catalog, indent=2, default=str), encoding="utf-8")


def save_item(item: dict, image_bytes: bytes | None = None) -> int:
    """Insert a wardrobe item directly into Postgres. Returns the new row ID."""
    from db.postgres import get_conn

    semantic_text = item.get("semantic_text") or build_semantic_text(item)

    with get_conn() as conn:
        row = conn.execute(
            """INSERT INTO wardrobe
            (category, subcategory, color, pattern, season, comfort,
             style_tags, suited_for, source_file, description, item_name,
             fabric, weather_suitability, style_vibe, occasion_context,
             photo_scene, place_type, place_name, place_activity, place_vibe,
             semantic_text, image_data, image_mime, source_photo)
            VALUES (%(category)s, %(subcategory)s, %(color)s, %(pattern)s,
                    %(season)s, %(comfort)s, %(style_tags)s, %(suited_for)s,
                    %(source_file)s, %(description)s, %(item_name)s,
                    %(fabric)s, %(weather_suitability)s, %(style_vibe)s,
                    %(occasion_context)s, %(photo_scene)s,
                    %(place_type)s, %(place_name)s, %(place_activity)s,
                    %(place_vibe)s, %(semantic_text)s,
                    %(image_data)s, %(image_mime)s, %(source_photo)s)
            RETURNING id""",
            {
                "category": item.get("category", ""),
                "subcategory": item.get("subcategory", ""),
                "color": item.get("color", ""),
                "pattern": item.get("pattern", "solid"),
                "season": item.get("season", "all_season"),
                "comfort": item.get("comfort", "casual"),
                "style_tags": json.dumps(item.get("style_tags", [])),
                "suited_for": item.get("suited_for", ""),
                "source_file": item.get("source_file", ""),
                "description": item.get("description", ""),
                "item_name": item.get("subcategory", ""),
                "fabric": item.get("fabric", ""),
                "weather_suitability": item.get("weather_suitability", ""),
                "style_vibe": item.get("style_vibe", ""),
                "occasion_context": item.get("occasion_context", ""),
                "photo_scene": item.get("photo_scene", ""),
                "place_type": item.get("place_type", ""),
                "place_name": item.get("place_name", ""),
                "place_activity": item.get("place_activity", ""),
                "place_vibe": item.get("place_vibe", ""),
                "semantic_text": semantic_text,
                "image_data": image_bytes,
                "image_mime": "image/png" if image_bytes else None,
                "source_photo": item.get("source_path", ""),
            },
        ).fetchone()
        conn.commit()
    return row["id"]


def embed_item(postgres_id: int, item: dict) -> str | None:
    """Build semantic text, embed as a chunk, and link back to the wardrobe row.

    Returns the chunk_id on success, None on failure.
    """
    from memory.vectorstore import VectorStore
    from memory.chunker import Chunk, _ensure_metadata
    from db.postgres import get_conn

    semantic_text = item.get("semantic_text") or build_semantic_text(item)

    # Update the wardrobe row with the semantic text
    with get_conn() as conn:
        conn.execute(
            "UPDATE wardrobe SET semantic_text = %s WHERE id = %s",
            (semantic_text, postgres_id),
        )
        conn.commit()

    chunk = Chunk(
        text=semantic_text,
        metadata=_ensure_metadata({
            "source": "wardrobe",
            "conversation_id": f"wardrobe_item_{postgres_id}",
            "title": f"{item.get('color', '')} {item.get('subcategory', '')}".strip(),
            "type": "wardrobe_item",
            "pillar": "SOCIAL",
            "dimension": "life",
            "classified": "true",
        }),
    )

    store = VectorStore()
    count = store.ingest([chunk])

    if count > 0:
        chunk_id = store._chunk_id(chunk.text, chunk.metadata)
        with get_conn() as conn:
            conn.execute(
                "UPDATE wardrobe SET chunk_id = %s, embedded_at = NOW() WHERE id = %s",
                (chunk_id, postgres_id),
            )
            conn.commit()
        return chunk_id
    return None
