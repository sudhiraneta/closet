"""
Wardrobe Outfit — outfit recommendation engine using semantic search,
weather data, and recency tracking.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, timezone

from wardrobe.vision import get_weather


def build_recency_tags(conn) -> dict[int, str]:
    """Score each wardrobe item by how recently it was suggested.

    Queries last 7 outfit recommendations from outfit_history.
    Returns {item_id: tag} where tag indicates recency:
      - "SUGGESTED TODAY"       -> suggested today (strongest avoid)
      - "SUGGESTED 1 DAY AGO"  -> yesterday
      - "SUGGESTED 2 DAYS AGO" -> etc.
    Items not in recent history get no tag.
    """
    rows = conn.execute(
        "SELECT top_id, bottom_id, dress_id, shoes_id, created_at "
        "FROM outfit_history ORDER BY created_at DESC LIMIT 7"
    ).fetchall()

    now = datetime.now(tz=timezone.utc)
    tags: dict[int, str] = {}

    for r in rows:
        days_ago = (now - r["created_at"]).days
        if days_ago == 0:
            label = "SUGGESTED TODAY"
        elif days_ago == 1:
            label = "SUGGESTED 1 DAY AGO"
        else:
            label = f"SUGGESTED {days_ago} DAYS AGO"

        for item_id in [r["top_id"], r["bottom_id"], r["dress_id"], r["shoes_id"]]:
            if item_id and item_id not in tags:
                tags[item_id] = label

    return tags


def geocode_city(city_name: str) -> tuple[float, float] | None:
    """Resolve a city name to (lat, lon) via Open-Meteo geocoding API."""
    import httpx
    try:
        resp = httpx.get(
            f"https://geocoding-api.open-meteo.com/v1/search?name={city_name}&count=1",
            timeout=5,
        )
        results = resp.json().get("results", [])
        if results:
            return results[0]["latitude"], results[0]["longitude"]
    except Exception:
        pass
    return None


def extract_city_from_prompt(prompt: str) -> str | None:
    """Extract a city/location name from a natural language prompt.

    Simple keyword extraction — looks for 'in <city>' patterns.
    """
    import re
    # Match "in NYC", "in New York", "in San Francisco, CA", etc.
    m = re.search(r'\bin\s+([A-Z][A-Za-z\s,]+?)(?:\s+for|\s+today|\s+this|\s+tonight|\s+tomorrow|$)', prompt)
    if m:
        return m.group(1).strip().rstrip(",")
    # Match city abbreviations
    for abbr, full in [("NYC", "New York"), ("SF", "San Francisco"), ("LA", "Los Angeles"),
                       ("DC", "Washington DC"), ("CHI", "Chicago")]:
        if abbr in prompt.upper().split():
            return full
    return None


def format_outfit_item(item: dict) -> dict:
    return {
        "id": item["id"],
        "category": item["category"],
        "subcategory": item["subcategory"],
        "color": item["color"],
        "description": item.get("description", ""),
        "image_url": f"/api/wardrobe/image/{item['id']}",
    }


def generate_outfit(prompt: str) -> dict:
    """Generate outfit recommendation from a natural language prompt.

    Examples:
        "I am in NYC for my bday today suggest some party outfits but suits the weather"
        "casual outfit for a hike in mild weather"
        "office meeting look for rainy day in Seattle"

    Pipeline:
    1. Extract city from prompt -> geocode -> fetch weather
    2. Combine prompt + weather context as the semantic search query
    3. Search wardrobe embeddings
    4. Hard filters: recency, slot selection, pattern clash
    5. Return outfit
    """
    from memory.vectorstore import VectorStore
    from db.postgres import get_conn

    # --- Step 1: Extract city and get weather ---
    city = extract_city_from_prompt(prompt)
    weather = {}
    if city:
        coords = geocode_city(city)
        if coords:
            weather = get_weather(lat=coords[0], lon=coords[1])

    if not weather or weather.get("error"):
        weather = get_weather()  # fallback to default location
        if not city:
            city = "local"

    temp_c = weather.get("temp_c", 20)
    temp_f = weather.get("temp_f", 68)
    condition = weather.get("condition", "clear")

    # --- Step 2: Build search query = user prompt + weather context ---
    weather_context = f"{temp_c}C {condition} weather"
    if "rain" in condition.lower() or "drizzle" in condition.lower():
        weather_context += ", rain resistant closed shoes"

    query = f"{prompt}. Weather: {weather_context}"

    # --- Step 2: Semantic search ---
    store = VectorStore()
    results = store.search(
        query=query,
        n_results=30,
        where={"type": "wardrobe_item"},
        max_distance=1.5,
    )

    if not results:
        return {"error": "No matching items found. Embed your wardrobe first (POST /wardrobe/reprocess).",
                "search_query": query}

    # --- Step 3: Map results back to wardrobe rows ---
    chunk_to_distance = {}
    for r in results:
        conv_id = r["metadata"].get("conversation_id", "")
        wid_str = conv_id.replace("wardrobe_item_", "") if conv_id.startswith("wardrobe_item_") else ""
        try:
            wid = int(wid_str)
            chunk_to_distance[wid] = r.get("distance", 1.0)
        except (ValueError, TypeError):
            continue

    if not chunk_to_distance:
        return {"error": "Could not map search results to wardrobe items.", "search_query": query}

    with get_conn() as conn:
        recency_tags = build_recency_tags(conn)
        rows = conn.execute(
            "SELECT id, category, subcategory, color, pattern, season, comfort, "
            "description, style_vibe, fabric "
            "FROM wardrobe WHERE id = ANY(%s)",
            (list(chunk_to_distance.keys()),),
        ).fetchall()

    # --- Step 4: Score and filter ---
    candidates = []
    for r in rows:
        r = dict(r)
        dist = chunk_to_distance.get(r["id"], 1.0)
        recency_penalty = 0.0
        if r["id"] in recency_tags:
            tag = recency_tags[r["id"]]
            if "TODAY" in tag:
                recency_penalty = 10.0  # banned
            elif "1 DAY" in tag:
                recency_penalty = 0.5
            elif "2 DAY" in tag:
                recency_penalty = 0.2
            else:
                recency_penalty = 0.1
        score = dist + recency_penalty
        candidates.append((score, r))

    candidates.sort(key=lambda x: x[0])

    # Group by category
    tops = [(s, i) for s, i in candidates if i["category"] == "tops"]
    bottoms = [(s, i) for s, i in candidates if i["category"] == "bottoms"]
    dresses = [(s, i) for s, i in candidates if i["category"] == "dresses"]
    shoes = [(s, i) for s, i in candidates if i["category"] == "shoes"]

    # Pick slots
    top_pick = tops[0][1] if tops else None
    bottom_pick = bottoms[0][1] if bottoms else None
    dress_pick = dresses[0][1] if dresses else None
    shoes_pick = shoes[0][1] if shoes else None

    # Dress vs top+bottom: pick whichever scored better
    use_dress = False
    if dress_pick and (not top_pick or not bottom_pick):
        use_dress = True
    elif dress_pick and top_pick and bottom_pick:
        tb_avg = (tops[0][0] + bottoms[0][0]) / 2
        use_dress = dresses[0][0] < tb_avg

    result = {}
    if use_dress and dress_pick:
        result["dress"] = format_outfit_item(dress_pick)
    else:
        if top_pick:
            result["top"] = format_outfit_item(top_pick)
        if bottom_pick:
            # Pattern clash: if both patterned, swap bottom for a solid one
            if (top_pick and top_pick["pattern"] != "solid"
                    and bottom_pick["pattern"] != "solid"):
                for _, alt in bottoms[1:]:
                    if alt["pattern"] == "solid":
                        bottom_pick = alt
                        break
            result["bottom"] = format_outfit_item(bottom_pick)

    if shoes_pick:
        result["shoes"] = format_outfit_item(shoes_pick)

    # Build reasoning from attributes
    items_desc = []
    for slot in ["top", "bottom", "dress", "shoes"]:
        if slot in result:
            items_desc.append(f"{result[slot]['color']} {result[slot]['subcategory']}")

    reasoning_parts = [f"For {city or 'your area'} at {temp_c}C {condition}"]
    if items_desc:
        reasoning_parts.append(f"— picked {', '.join(items_desc)}.")
    result["reasoning"] = " ".join(reasoning_parts)
    result["prompt"] = prompt
    result["search_query"] = query
    result["weather"] = weather
    result["city"] = city

    # Log to outfit_history
    top_id = result.get("top", {}).get("id")
    bottom_id = result.get("bottom", {}).get("id")
    dress_id = result.get("dress", {}).get("id")
    shoes_id = result.get("shoes", {}).get("id")
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO outfit_history (top_id, bottom_id, dress_id, shoes_id, "
                "weather_temp, weather_condition, style, reasoning, city) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (top_id, bottom_id, dress_id, shoes_id,
                 temp_f, condition, prompt, result["reasoning"], city or ""),
            )
            conn.commit()
    except Exception:
        pass

    return result
