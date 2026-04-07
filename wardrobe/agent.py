"""
Outfit ReAct Agent — conversational outfit recommender.

Uses a Reason → Act (tool call) → Observe → Reason loop:

1. Ask city → get weather
2. Ask occasion/style (if not given)
3. Query closet → compose outfit → recommend
4. Ask "Is any of this in laundry?"
5. If yes → exclude those, keep session preferences → recommend new outfit
6. Loop 4-5 until user is happy

Session state persists: city, weather, style, excluded items, all previous
recommendations. Each new recommendation avoids everything already suggested.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dataclasses import dataclass, field

from wardrobe.outfit import (
    geocode_city, format_outfit_item, build_recency_tags,
)
from wardrobe.vision import get_weather


# ---------------------------------------------------------------------------
# Session state — persists across the conversation
# ---------------------------------------------------------------------------

@dataclass
class OutfitSession:
    """Holds all context for a multi-turn outfit conversation."""
    city: str = ""
    weather: dict = field(default_factory=dict)
    style: str = ""
    occasion: str = ""
    excluded_ids: set[int] = field(default_factory=set)   # laundry + previously suggested
    suggested_ids: set[int] = field(default_factory=set)   # all items recommended this session
    current_outfit: dict = field(default_factory=dict)
    step: str = "start"  # start → city → weather → style → recommend → laundry → done


# ---------------------------------------------------------------------------
# Tools the agent can call
# ---------------------------------------------------------------------------

def tool_get_weather(session: OutfitSession, city: str) -> dict:
    """Resolve city → geocode → fetch weather. Updates session."""
    session.city = city
    coords = geocode_city(city)
    if coords:
        session.weather = get_weather(lat=coords[0], lon=coords[1])
    else:
        session.weather = get_weather()  # fallback
    return session.weather


def tool_query_closet(session: OutfitSession) -> dict:
    """Search wardrobe embeddings with session context. Returns outfit."""
    from memory.vectorstore import VectorStore
    from db.postgres import get_conn

    # Build query from session
    temp_c = session.weather.get("temp_c", 20)
    condition = session.weather.get("condition", "clear")
    weather_ctx = f"{temp_c}C {condition}"
    if "rain" in condition.lower() or "drizzle" in condition.lower():
        weather_ctx += ", rain resistant closed shoes"

    parts = []
    if session.occasion:
        parts.append(session.occasion)
    if session.style:
        parts.append(f"{session.style} style")
    parts.append(f"Weather: {weather_ctx}")
    query = " ".join(parts)

    # Search
    store = VectorStore()
    results = store.search(
        query=query,
        n_results=30,
        where={"type": "wardrobe_item"},
        max_distance=1.5,
    )

    if not results:
        return {"error": "No matching items. Add more to your wardrobe."}

    # Map to wardrobe rows
    chunk_to_dist = {}
    for r in results:
        conv_id = r["metadata"].get("conversation_id", "")
        wid_str = conv_id.replace("wardrobe_item_", "") if conv_id.startswith("wardrobe_item_") else ""
        try:
            chunk_to_dist[int(wid_str)] = r.get("distance", 1.0)
        except (ValueError, TypeError):
            continue

    if not chunk_to_dist:
        return {"error": "Could not map results to wardrobe items."}

    with get_conn() as conn:
        recency_tags = build_recency_tags(conn)
        rows = conn.execute(
            "SELECT id, category, subcategory, color, pattern, season, comfort, "
            "description, style_vibe, fabric "
            "FROM wardrobe WHERE id = ANY(%s)",
            (list(chunk_to_dist.keys()),),
        ).fetchall()

    # Score + filter (exclude laundry + previously suggested)
    candidates = []
    for r in rows:
        r = dict(r)
        if r["id"] in session.excluded_ids:
            continue

        dist = chunk_to_dist.get(r["id"], 1.0)
        penalty = 0.0
        if r["id"] in recency_tags:
            tag = recency_tags[r["id"]]
            if "TODAY" in tag:
                penalty = 10.0
            elif "1 DAY" in tag:
                penalty = 0.5
            elif "2 DAY" in tag:
                penalty = 0.2
            else:
                penalty = 0.1
        # Extra penalty for items suggested this session
        if r["id"] in session.suggested_ids:
            penalty += 5.0

        candidates.append((dist + penalty, r))

    candidates.sort(key=lambda x: x[0])

    # Group by category
    by_cat: dict[str, list] = {}
    for score, item in candidates:
        by_cat.setdefault(item["category"], []).append((score, item))

    tops = by_cat.get("tops", [])
    bottoms = by_cat.get("bottoms", [])
    dresses = by_cat.get("dresses", [])
    shoes = by_cat.get("shoes", [])

    top_pick = tops[0][1] if tops else None
    bottom_pick = bottoms[0][1] if bottoms else None
    dress_pick = dresses[0][1] if dresses else None
    shoes_pick = shoes[0][1] if shoes else None

    # Dress vs top+bottom
    use_dress = False
    if dress_pick and (not top_pick or not bottom_pick):
        use_dress = True
    elif dress_pick and top_pick and bottom_pick:
        tb_avg = (tops[0][0] + bottoms[0][0]) / 2
        use_dress = dresses[0][0] < tb_avg

    outfit = {}
    if use_dress and dress_pick:
        outfit["dress"] = format_outfit_item(dress_pick)
    else:
        if top_pick:
            outfit["top"] = format_outfit_item(top_pick)
        if bottom_pick:
            if (top_pick and top_pick["pattern"] != "solid"
                    and bottom_pick["pattern"] != "solid"):
                for _, alt in bottoms[1:]:
                    if alt["pattern"] == "solid":
                        bottom_pick = alt
                        break
            outfit["bottom"] = format_outfit_item(bottom_pick)

    if shoes_pick:
        outfit["shoes"] = format_outfit_item(shoes_pick)

    # Track what we suggested
    for slot in ["top", "bottom", "dress", "shoes"]:
        if slot in outfit:
            session.suggested_ids.add(outfit[slot]["id"])

    # Build reasoning
    items_desc = [f"{outfit[s]['color']} {outfit[s]['subcategory']}"
                  for s in ["top", "bottom", "dress", "shoes"] if s in outfit]
    temp_c = session.weather.get("temp_c", "?")
    condition = session.weather.get("condition", "")
    reasoning = f"For {session.city} at {temp_c}C {condition} — {', '.join(items_desc)}."

    outfit["reasoning"] = reasoning
    outfit["weather"] = session.weather
    outfit["city"] = session.city
    session.current_outfit = outfit

    # Log to history
    _log_outfit(session, outfit)

    return outfit


def tool_exclude_laundry(session: OutfitSession, item_ids: list[int]) -> str:
    """Mark items as in laundry — excluded from future recommendations."""
    for iid in item_ids:
        session.excluded_ids.add(iid)
    names = []
    from db.postgres import get_conn
    with get_conn() as conn:
        for iid in item_ids:
            row = conn.execute(
                "SELECT subcategory, color FROM wardrobe WHERE id = %s", (iid,)
            ).fetchone()
            if row:
                names.append(f"{row['color']} {row['subcategory']}")
    return f"Got it — excluding {', '.join(names)} from recommendations."


def _log_outfit(session: OutfitSession, outfit: dict):
    """Log the recommendation to outfit_history."""
    from db.postgres import get_conn
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO outfit_history (top_id, bottom_id, dress_id, shoes_id, "
                "weather_temp, weather_condition, style, reasoning, city) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    outfit.get("top", {}).get("id"),
                    outfit.get("bottom", {}).get("id"),
                    outfit.get("dress", {}).get("id"),
                    outfit.get("shoes", {}).get("id"),
                    session.weather.get("temp_f"),
                    session.weather.get("condition"),
                    session.style or session.occasion,
                    outfit.get("reasoning", ""),
                    session.city or "",
                ),
            )
            conn.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Agent step — processes one user message, returns response + next action
# ---------------------------------------------------------------------------

def agent_step(session: OutfitSession, user_input: str) -> dict:
    """Process one turn of the outfit conversation.

    Returns:
        {
            "message": str,          # Agent's response text
            "outfit": dict | None,   # Outfit if recommended, else None
            "action": str,           # What the agent needs next: "ask_city", "ask_style",
                                     #   "show_outfit", "ask_laundry", "done"
            "options": list | None,  # Suggested options for the user (buttons)
        }
    """
    text = user_input.strip().lower()

    # --- Step: Start / extract initial context ---
    if session.step == "start":
        # Try to extract city from the initial prompt
        from wardrobe.outfit import extract_city_from_prompt
        city = extract_city_from_prompt(user_input)

        # Check for style/occasion keywords
        style_words = {"casual", "formal", "smart casual", "athletic", "party",
                       "date", "office", "brunch", "hiking", "gym", "travel"}
        found_style = [w for w in style_words if w in text]

        if city:
            tool_get_weather(session, city)
            if found_style:
                session.style = found_style[0]
                session.occasion = user_input
                session.step = "recommend"
                outfit = tool_query_closet(session)
                session.step = "laundry"
                return {
                    "message": (
                        f"Here's what I'd recommend for {session.city} "
                        f"({session.weather.get('temp_c')}C, {session.weather.get('condition')}):"
                    ),
                    "outfit": outfit,
                    "action": "ask_laundry",
                    "options": ["Looks good!", "Something's in the laundry", "Try another style"],
                }
            else:
                session.occasion = user_input
                session.step = "style"
                return {
                    "message": (
                        f"Got it — {session.city} "
                        f"({session.weather.get('temp_c')}C, {session.weather.get('condition')}). "
                        f"What's the vibe?"
                    ),
                    "outfit": None,
                    "action": "ask_style",
                    "options": ["Casual", "Smart casual", "Formal", "Party", "Athletic"],
                }
        else:
            session.occasion = user_input
            session.step = "city"
            return {
                "message": "Where are you today?",
                "outfit": None,
                "action": "ask_city",
                "options": ["Sunnyvale, CA", "San Francisco, CA", "New York, NY"],
            }

    # --- Step: City ---
    if session.step == "city":
        tool_get_weather(session, user_input.strip())
        session.step = "style"
        return {
            "message": (
                f"{session.city} — {session.weather.get('temp_c')}C, "
                f"{session.weather.get('condition')}. What's the vibe?"
            ),
            "outfit": None,
            "action": "ask_style",
            "options": ["Casual", "Smart casual", "Formal", "Party", "Athletic"],
        }

    # --- Step: Style ---
    if session.step == "style":
        session.style = user_input.strip()
        session.step = "recommend"
        outfit = tool_query_closet(session)
        session.step = "laundry"
        return {
            "message": f"Here's a {session.style} look for {session.city}:",
            "outfit": outfit,
            "action": "ask_laundry",
            "options": ["Looks good!", "Something's in the laundry", "Try another style"],
        }

    # --- Step: Laundry check ---
    if session.step == "laundry":
        if "good" in text or "perfect" in text or "love" in text or "done" in text or "yes" in text:
            session.step = "done"
            return {
                "message": "You're all set! Have a great day.",
                "outfit": session.current_outfit,
                "action": "done",
                "options": None,
            }

        if "laundry" in text or "wash" in text or "dirty" in text:
            # Show current outfit items so user can pick which is in laundry
            items = []
            for slot in ["top", "bottom", "dress", "shoes"]:
                if slot in session.current_outfit and slot not in ("reasoning", "weather", "city"):
                    item = session.current_outfit[slot]
                    if isinstance(item, dict) and "id" in item:
                        items.append(item)
            session.step = "pick_laundry"
            return {
                "message": "Which items are in the laundry? Pick the ones to exclude:",
                "outfit": None,
                "action": "pick_laundry",
                "options": [f"{i['color']} {i['subcategory']} (id:{i['id']})" for i in items],
            }

        if "another" in text or "different" in text or "try" in text or "new" in text:
            # Exclude current outfit and recommend fresh
            for slot in ["top", "bottom", "dress", "shoes"]:
                if slot in session.current_outfit:
                    item = session.current_outfit[slot]
                    if isinstance(item, dict) and "id" in item:
                        session.excluded_ids.add(item["id"])
            outfit = tool_query_closet(session)
            return {
                "message": f"Here's another option for {session.city}:",
                "outfit": outfit,
                "action": "ask_laundry",
                "options": ["Looks good!", "Something's in the laundry", "Try another style"],
            }

        # Fallback — treat as style change
        session.style = user_input.strip()
        for slot in ["top", "bottom", "dress", "shoes"]:
            if slot in session.current_outfit:
                item = session.current_outfit[slot]
                if isinstance(item, dict) and "id" in item:
                    session.excluded_ids.add(item["id"])
        outfit = tool_query_closet(session)
        return {
            "message": f"Here's a {session.style} look instead:",
            "outfit": outfit,
            "action": "ask_laundry",
            "options": ["Looks good!", "Something's in the laundry", "Try another style"],
        }

    # --- Step: Pick laundry items ---
    if session.step == "pick_laundry":
        # Parse item IDs from user input
        import re
        ids_found = [int(x) for x in re.findall(r'id:(\d+)', user_input)]
        if not ids_found:
            # Try parsing as numbers directly
            ids_found = [int(x) for x in re.findall(r'\d+', user_input)]

        if ids_found:
            msg = tool_exclude_laundry(session, ids_found)
            # Recommend new outfit excluding laundry
            outfit = tool_query_closet(session)
            session.step = "laundry"
            return {
                "message": f"{msg}\n\nHere's an updated outfit:",
                "outfit": outfit,
                "action": "ask_laundry",
                "options": ["Looks good!", "Something's in the laundry", "Try another style"],
            }
        else:
            session.step = "laundry"
            outfit = tool_query_closet(session)
            return {
                "message": "No worries — here's a fresh outfit:",
                "outfit": outfit,
                "action": "ask_laundry",
                "options": ["Looks good!", "Something's in the laundry", "Try another style"],
            }

    # --- Step: Done ---
    if session.step == "done":
        # Reset for new conversation
        session.step = "start"
        session.excluded_ids.clear()
        session.suggested_ids.clear()
        return agent_step(session, user_input)

    # Fallback
    return {
        "message": "Tell me what you're looking for — occasion, city, and style!",
        "outfit": None,
        "action": "ask_city",
        "options": None,
    }
