"""
Wardrobe Dedup — perceptual hashing, timestamp grouping, and semantic
deduplication for wardrobe photos and items.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, timezone

from PIL import Image

HASH_SIZE = 8                  # perceptual hash grid size
HASH_THRESHOLD = 10            # max hamming distance to consider a duplicate
TIMESTAMP_GROUP_SECS = 300     # photos within 5 min are likely same outfit


# ---------------------------------------------------------------------------
# Perceptual hashing for duplicate detection
# ---------------------------------------------------------------------------

def perceptual_hash(path: Path) -> str:
    """Compute a simple average-hash (aHash) for an image. Returns hex string."""
    img = Image.open(path).convert("L")  # grayscale
    img = img.resize((HASH_SIZE, HASH_SIZE), Image.LANCZOS)
    pixels = list(img.getdata())
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if p > avg else "0" for p in pixels)
    return format(int(bits, 2), f"0{HASH_SIZE * HASH_SIZE // 4}x")


def hamming_distance(h1: str, h2: str) -> int:
    """Hamming distance between two hex hash strings."""
    n1, n2 = int(h1, 16), int(h2, 16)
    return bin(n1 ^ n2).count("1")


def is_duplicate(new_hash: str, existing_hashes: dict) -> str | None:
    """Check if new_hash is a near-duplicate of any existing hash.

    Returns the matching filename if duplicate, None otherwise.
    """
    for filename, h in existing_hashes.items():
        if hamming_distance(new_hash, h) <= HASH_THRESHOLD:
            return filename
    return None


# ---------------------------------------------------------------------------
# Timestamp grouping — pick best photo from burst/sequence
# ---------------------------------------------------------------------------

def extract_timestamp(path: Path) -> int | None:
    """Extract Unix timestamp from PXL/IMG filename pattern.

    PXL_20260215_004922213 -> 2026-02-15 00:49:22
    IMG_20210925_161301    -> 2021-09-25 16:13:01
    """
    import re
    m = re.search(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", path.stem)
    if m:
        try:
            dt = datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3)),
                int(m.group(4)), int(m.group(5)), int(m.group(6)),
                tzinfo=timezone.utc,
            )
            return int(dt.timestamp())
        except ValueError:
            pass
    return None


def pick_best_from_group(paths: list[Path]) -> Path:
    """From a group of near-simultaneous photos, pick the best one (largest file = highest quality)."""
    return max(paths, key=lambda p: p.stat().st_size)


def group_by_timestamp(images: list[Path]) -> list[Path]:
    """Group photos by timestamp, keep only the best from each burst.

    Photos taken within TIMESTAMP_GROUP_SECS of each other are grouped.
    Returns deduplicated list with one photo per group + ungroupable photos.
    """
    timestamped = []
    no_timestamp = []

    for img in images:
        ts = extract_timestamp(img)
        if ts:
            timestamped.append((ts, img))
        else:
            no_timestamp.append(img)

    if not timestamped:
        return images

    timestamped.sort(key=lambda x: x[0])

    groups: list[list[Path]] = []
    current_group = [timestamped[0][1]]
    current_ts = timestamped[0][0]

    for ts, path in timestamped[1:]:
        if ts - current_ts <= TIMESTAMP_GROUP_SECS:
            current_group.append(path)
        else:
            groups.append(current_group)
            current_group = [path]
        current_ts = ts

    groups.append(current_group)

    result = []
    for group in groups:
        best = pick_best_from_group(group)
        if len(group) > 1:
            skipped = [p.name for p in group if p != best]
            print(f"  BURST: {len(group)} photos within {TIMESTAMP_GROUP_SECS}s — "
                  f"keeping {best.name}, skipping {skipped}")
        result.append(best)

    return result + no_timestamp


# ---------------------------------------------------------------------------
# Item-level dedup — compare source photo against existing items' source photos
# ---------------------------------------------------------------------------

# Cache source photo hashes so we don't recompute for each item in the same photo
_source_hash_cache: dict[str, str] = {}


def _get_source_hash(source_file: str, catalog_items: list[dict]) -> str | None:
    """Get the perceptual hash of an existing item's source photo."""
    if source_file in _source_hash_cache:
        return _source_hash_cache[source_file]

    for item in catalog_items:
        if item.get("source_file") == source_file:
            src = item.get("source_path", "")
            if src and Path(src).exists():
                try:
                    h = perceptual_hash(Path(src))
                    _source_hash_cache[source_file] = h
                    return h
                except Exception:
                    pass
    return None


def _find_duplicate_source(img_path: Path, category_items: list[dict], threshold: int = 10) -> dict | None:
    """Check if a source photo visually matches any existing item's source photo in the same category.

    Runs BEFORE the Gemini call to avoid wasting API calls on duplicates.
    Only compares within the given category (e.g. dress vs dress, not dress vs shoe).
    """
    try:
        new_hash = perceptual_hash(img_path)
    except Exception:
        return None

    for existing in category_items:
        ext_source = existing.get("source_file", "")
        ext_path = existing.get("source_path", "")

        if not ext_path or not Path(ext_path).exists():
            continue

        ext_hash = _get_source_hash(ext_source, category_items)
        if not ext_hash:
            try:
                ext_hash = perceptual_hash(Path(ext_path))
                _source_hash_cache[ext_source] = ext_hash
            except Exception:
                continue

        if hamming_distance(new_hash, ext_hash) <= threshold:
            return existing

    return None


def build_semantic_text(item: dict) -> str:
    """Build a natural language description of a wardrobe item for embedding.

    The resulting text is designed to match well against queries like:
    "warm outfit for 10C rainy day going to coffee shop"
    "professional look for office meeting in mild weather"
    """
    parts = []

    # Core identity
    color = item.get("color", "")
    fabric = item.get("fabric", "")
    subcat = item.get("subcategory", "")
    desc = item.get("description", "")
    parts.append(f"{color} {fabric} {subcat}. {desc}.")

    # Weather suitability (critical for matching)
    weather = item.get("weather_suitability", "")
    if weather:
        parts.append(f"Weather: {weather}.")

    # Style and vibe
    vibe = item.get("style_vibe", "")
    comfort = item.get("comfort", "")
    if vibe or comfort:
        parts.append(f"Style: {vibe or ''} {comfort or ''}.")

    # Occasion suitability
    suited = item.get("suited_for", "")
    occasion = item.get("occasion_context", "")
    if suited or occasion:
        parts.append(f"Good for: {suited or occasion}.")

    # Season
    season = item.get("season", "")
    if season and season != "all_season":
        parts.append(f"Best in {season.replace('_', ' ')}.")

    # Place context from source photo
    place_type = item.get("place_type", "")
    place_activity = item.get("place_activity", "")
    if place_type or place_activity:
        parts.append(f"Worn at: {place_type} {place_activity}.")

    return " ".join(parts).strip()


def item_exists_in_wardrobe(item: dict, threshold: float = 0.25) -> int | None:
    """Check if a semantically similar item already exists in the wardrobe.

    Embeds the item's semantic text and searches existing wardrobe_item
    vectors in the same category via HNSW index (O(1), not O(n)).

    Returns the existing item's Postgres ID if a match is found
    within the cosine distance threshold, else None.
    """
    from memory.vectorstore import VectorStore
    from db.postgres import get_conn

    semantic_text = build_semantic_text(item)
    store = VectorStore()
    results = store.search(
        query=semantic_text,
        n_results=3,
        where={"type": "wardrobe_item"},
        max_distance=threshold,
    )

    if not results:
        return None

    # Check same category among top matches
    for match in results:
        conv_id = match["metadata"].get("conversation_id", "")
        wid_str = conv_id.replace("wardrobe_item_", "") if conv_id.startswith("wardrobe_item_") else ""
        try:
            wid = int(wid_str)
        except (ValueError, TypeError):
            continue

        with get_conn() as conn:
            row = conn.execute(
                "SELECT id, category FROM wardrobe WHERE id = %s", (wid,),
            ).fetchone()

        if row and row["category"] == item.get("category", ""):
            return row["id"]

    return None
