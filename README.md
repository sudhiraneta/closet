# Closet

A tool-using **ReAct-style agent** sitting on top of a **batch ETL/indexing pipeline** for wardrobe management and outfit recommendation.

The recommender is a **single-agent orchestrator with tool calls** — not multi-agent. One LLM brain that follows the **Reason → Act (tool call) → Observe → Reason → final answer** loop. The agent's tools are:

| Tool | What it does | When called |
|------|-------------|-------------|
| `ask_user_for_city` | Ask the user where they are today | Start of session, if city not in prompt |
| `get_weather` | Geocode city → fetch real-time weather from Open-Meteo | After city is known |
| `get_style_preferences` | Ask occasion, style, comfort level | If not provided in the initial prompt |
| `query_closet` | Semantic search against wardrobe embeddings (pgvector HNSW) | After city + weather + style are locked in |
| `compose_outfit` | Pick top+bottom or dress, add shoes, apply pattern/recency filters | After search results come back |

The pipeline beneath it handles photo ingestion, garment extraction, deduplication, and semantic indexing — all offline, before the agent ever runs.

## Architecture

```
                         USER
                          |
                    [Natural Language]
                    "Party outfit for NYC tonight"
                          |
            ┌─────────────────────────────┐
            │         REACT AGENT         │
            │                             │
            │  Reason → Act → Observe     │
            │     ↓       ↓       ↓       │
            │  "Need    tool    "Got      │
            │   weather" call    12C,     │
            │            ↓      cloudy"   │
            │         Reason → Act → ...  │
            └──────┬──────┬──────┬────────┘
                   │      │      │
         ┌─────────┤      │      ├─────────┐
         │         │      │      │         │
  ask_user_    get_      get_   query_   compose_
  for_city   weather   style   closet    outfit
    ()        ()     prefs()    ()        ()
              │                  │
              │         ┌────────┴────────┐
         Open-Meteo     │                 │
           API     wardrobe table    chunks table
                    (Postgres)     (pgvector HNSW)
                         │
              ┌──────────┴──────────┐
              │                     │
        Batch ETL Pipeline     Garment Images
        (process_inbox_photos)  (Gemini Image Gen)
              │
      ┌───────┼───────┼───────┐
      │       │       │       │
   Layer 1  Layer 2  Layer 3  Layer 4
   Burst    Hash     Source   Semantic
   Dedup    Dedup    Dedup    Dedup
```

## Two Systems

### 1. Batch ETL Pipeline (Offline)

Processes photos into searchable wardrobe items. Runs when you drop photos in the inbox.

```
Photo → Gemini Vision → enriched metadata → garment image → Postgres + pgvector embedding
```

### 2. ReAct Agent (Online)

Conversational outfit recommender. Runs when you ask for an outfit.

```
User prompt → [reason] → tool calls → [observe] → recommend → laundry check → loop
```

---

## How the Agent Works (ReAct Pattern)

The agent (`wardrobe/agent.py`) implements the **ReAct** (Reasoning + Acting) pattern:

```
                ┌──────────┐
                │  Reason  │ ← "User said NYC + party. I need weather."
                └────┬─────┘
                     │
                ┌────▼─────┐
                │   Act    │ ← get_weather("NYC")
                └────┬─────┘
                     │
                ┌────▼─────┐
                │ Observe  │ ← "12C, partly cloudy"
                └────┬─────┘
                     │
                ┌────▼─────┐
                │  Reason  │ ← "Cool evening + party = dress + boots"
                └────┬─────┘
                     │
                ┌────▼─────┐
                │   Act    │ ← query_closet(style="party", weather=12C)
                └────┬─────┘
                     │
                ┌────▼─────┐
                │ Observe  │ ← [midi sundress, ankle boots]
                └────┬─────┘
                     │
                ┌────▼─────┐
                │   Act    │ ← compose_outfit() + ask about laundry
                └──────────┘
```

### Full Conversation Example

```
Turn 1: "I am in NYC for my bday, party outfit please"

  [Reason]   Parse prompt → city=NYC, occasion=bday, style=party
  [Act]      ask_user_for_city → already extracted "NYC" from prompt, skip
  [Act]      get_weather("NYC") → 12C, partly cloudy
  [Act]      get_style_preferences → already extracted "party" from prompt, skip
  [Act]      query_closet(style="party", weather=12C, city="NYC")
  [Observe]  Search returned: sundress (score 0.31), boots (score 0.38)
  [Act]      compose_outfit → midi sundress + ankle boots
  [Output]   "Here's what I'd recommend for NYC (12C, partly cloudy):"
             → Shows outfit
             → "Is anything in the laundry?"

Turn 2: "The sundress is in the laundry"

  [Reason]   User says sundress is unavailable. Exclude id:177 for this session.
  [Act]      exclude_laundry([177]) → session.excluded_ids = {177}
  [Act]      query_closet(exclude={177}) → search again, sundress filtered out
  [Observe]  Next best: wrap dress (score 0.35) + sneakers (score 0.40)
  [Act]      compose_outfit → wrap dress + chunky sneakers
  [Output]   "Got it — here's an updated outfit:"
             → Shows new outfit (sundress gone, replaced)

Turn 3: "Try something different"

  [Reason]   User wants another option. Exclude current outfit too.
  [Act]      Add current outfit IDs to excluded → {177, 159, 164}
  [Act]      query_closet(exclude={177, 159, 164}) → next best items
  [Act]      compose_outfit → different combination
  [Output]   "Here's another option:"

Turn 4: "Looks good!"

  [Reason]   User is satisfied.
  [Output]   "You're all set! Have a great day."
             → Session ends. All exclusions cleared.
```

### Session State

Lives in memory only — **not persisted**. Laundry items are forgotten when the session ends.

| State | Scope | Purpose |
|-------|-------|---------|
| `city` + `weather` | Fetched once per session | No re-asking, locked in from Turn 1 |
| `style` / `occasion` | Locked from Turn 1 | Consistent vibe across re-rolls |
| `excluded_ids` | Session-only | Laundry + rejected outfits. Gone when session ends. |
| `suggested_ids` | Session-only | Everything recommended. Avoided in re-rolls. |
| `current_outfit` | Updated each turn | What's currently shown to the user |

### Agent Tools (implemented in `agent.py`)

| Tool | Function | When called |
|------|----------|-------------|
| `ask_user_for_city` | Returns city options or parses from prompt | Turn 1, if city not detected |
| `get_weather(city)` | Geocode → Open-Meteo API → real-time conditions | After city is known |
| `get_style_preferences` | Returns style options or parses from prompt | Turn 1, if style not detected |
| `query_closet(session)` | Embed query → pgvector HNSW search → filter by exclusions | Every recommendation turn |
| `compose_outfit(candidates)` | Pick slots (top+bottom or dress + shoes), pattern clash check | After search results |
| `exclude_laundry(ids)` | Add to session.excluded_ids (session-only, not permanent) | When user flags laundry items |

---

## How Photo Ingestion Works

### Step 1: Photo Analysis (Gemini Vision)

Each photo is sent to **Gemini 2.5 Flash** with a structured prompt that extracts per garment:

| Field | Example | Purpose |
|-------|---------|---------|
| `category` | tops, bottoms, dresses, shoes | Slot for outfit assembly |
| `subcategory` | ribbed crew-neck sweater | Specific garment type |
| `color` | dark brown | Visual identity |
| `fabric` | chunky knit wool | Weather suitability signal |
| `weather_suitability` | "warm layer for 0-10C" | Natural language, embeds well |
| `style_vibe` | cozy-casual | Aesthetic matching |
| `suited_for` | coffee run, everyday | Occasion matching |
| `scene` | park, autumn, casual outing | Context from source photo |

### Step 2: Garment Image Generation (Gemini Image Gen)

For each detected item, a **second Gemini call** generates a clean catalog-style product image:

```
Input:  Full photo of person wearing outfit
Prompt: "Extract ONLY this specific top: dark brown knit V-neck sweater.
         Generate a clean product image, laid flat, white background,
         no face, no person — like a Zara product page."
Output: Clean PNG of just that garment
```

The prompt includes the **specific item description from Step 1** so Gemini extracts the right garment when multiple items share a category (e.g. t-shirt + jacket are both "tops").

### Step 3: Semantic Embedding

Each item's metadata is combined into a ~60-word **semantic text**:

```
"dark brown chunky knit wool V-neck sweater. Thick ribbed texture, cozy and warm.
Weather: warm insulating layer for cool to cold weather 5-15C.
Style: cozy-casual. Good for: everyday wear, coffee run.
Best in fall. Worn at: residential, posing outdoors in autumn."
```

This text is embedded with **all-MiniLM-L6-v2** (384 dimensions) and stored in pgvector. At query time, the user's prompt + weather context is embedded and searched against these vectors via HNSW index — **O(1), ~60ms**.

---

## 4-Layer Deduplication

The pipeline prevents duplicate items at four levels, cheapest first:

```
Photo arrives
  │
  ├─ Layer 1: BURST DEDUP (free)
  │   Photos within 300s of each other → keep largest file only.
  │   "PXL_20260215_004920750" and "004922213" (2s apart) → skip one.
  │
  ├─ Layer 2: PERCEPTUAL HASH (cheap, local)
  │   8x8 grayscale average-hash → hamming distance ≤ 10 = duplicate.
  │   Catches visually identical photos with different filenames.
  │
  ├─ Layer 3: SOURCE FILE CHECK (1 SQL query)
  │   Skip if source_file already in Postgres wardrobe table.
  │   Prevents reprocessing the exact same photo.
  │
  └─ Layer 4: SEMANTIC DEDUP (1 embedding + 1 HNSW search, ~60ms)
      After Gemini Vision extracts items, embed the item's semantic text
      and search existing wardrobe_item vectors in the same category.
      If cosine distance < 0.15 → duplicate.

      "black jersey leggings" ≈ "black slim-fit leggings" → SKIP
      "black jersey leggings" ≠ "red striped button-up shirt" → ADD

      This runs BEFORE garment image generation (the expensive step),
      so duplicates never trigger a Gemini image gen call.
```

| Layer | What it catches | Cost | When |
|-------|----------------|------|------|
| Burst | Same outfit, rapid shutter | Free | Before any API call |
| Hash | Same photo, different name | Local PIL | Before any API call |
| Source | Same file reprocessed | 1 SQL | Before any API call |
| Semantic | Same garment across different photos | ~60ms | After Vision, before image gen |

---

## Project Structure

```
closet/
├── wardrobe/
│   ├── __init__.py     # Package exports
│   ├── agent.py        # ReAct outfit agent (conversational multi-turn)
│   ├── vision.py       # Gemini Vision analysis + garment image generation
│   ├── dedup.py        # 4-layer deduplication pipeline
│   ├── store.py        # Postgres save + pgvector embedding
│   ├── builder.py      # Batch ETL pipeline (process_inbox_photos)
│   ├── outfit.py       # Core outfit search (semantic search + scoring)
│   ├── routes.py       # FastAPI endpoints (/wardrobe/*)
│   └── page.py         # Streamlit UI (Closet, Outfit, Add New)
├── migrations/
│   └── 002_wardrobe_enrichment.sql
└── README.md
```

## Setup

Shared infrastructure with [ai-twin](https://github.com/sudhiraneta/ai-twin):

```bash
# Requires: Postgres 17 + pgvector on port 5433, Python 3.13+
# Run migration
psql -p 5433 ai_twin -f migrations/002_wardrobe_enrichment.sql

# Environment
GOOGLE_API_KEY=...    # Gemini (Vision + Image Gen + Chat)
DATABASE_URL=postgresql://...@localhost:5433/ai_twin
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/wardrobe/items` | GET | List all wardrobe items |
| `/wardrobe/image/{id}` | GET | Serve garment image |
| `/wardrobe/outfit?prompt=...` | POST | Get outfit recommendation |
| `/wardrobe/inbox` | POST | Process photos in inbox folder |
| `/wardrobe/items/add` | POST | Upload a single photo |
| `/wardrobe/reprocess` | POST | Re-analyze all items with enriched prompt |

## Tech Stack

- **Gemini 2.5 Flash** — Vision analysis + garment image generation
- **PostgreSQL 17 + pgvector** — wardrobe storage + semantic vector search (HNSW)
- **all-MiniLM-L6-v2** — 384-dim embeddings for semantic text
- **Open-Meteo** — real-time weather (free, no API key)
- **FastAPI** — API server
- **Streamlit** — UI
