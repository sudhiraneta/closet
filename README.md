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

## ReAct Agent Flow

![Closet Agent Flow](docs/closet_diagram.png)

### The 6-Step Loop

| Step | Tool | What happens |
|------|------|-------------|
| **1. Ask city** | `ask_user_for_city` | "Where are you today?" — extracts city from prompt or asks the user |
| **2. Get weather** | `get_weather` | Geocodes city → fetches real-time weather from Open-Meteo. **Fresh fetch every session, no cache.** |
| **3. Ask occasion/style** | `get_style_preferences` | "What's the occasion? Any style preferences?" — parses from prompt or presents options |
| **4. Check laundry** | `exclude_laundry` | "Anything in the laundry I should exclude?" — user picks items to skip |
| **5. Query closet** | `query_closet` | Semantic search with all context (weather + style + exclusions) against pgvector embeddings |
| **6. Compose outfit** | `compose_outfit` | Pick items by slot (top+bottom or dress + shoes), apply pattern clash rules, return recommendation |

After step 6, the loop goes back to step 4 — user can flag laundry, ask for a different style, or say "looks good" to exit.

### Side Loops

**Weather** — Always fetched live from Open-Meteo at the start of each session. No caching. If the user starts a new session later the same day, weather is fetched again (conditions change throughout the day).

**Laundry** — Session-only. `excluded_ids` lives in the `OutfitSession` dataclass in memory, not in Postgres. When the session ends, laundry exclusions are gone. No permanent flag on items. The loop between steps 4→5→6 can repeat as many times as needed — each iteration excludes more items and recommends from what's left.

**Re-rolls** — When the user says "try something different", all items from the current outfit are added to `excluded_ids` + `suggested_ids`, and the agent loops back to step 5 with those exclusions. Same city, weather, and style — just different items.

---

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

### 3 LLM Calls Per Item

Each garment goes through **3 separate LLM/model calls**, each with a distinct purpose:

```
Photo (person wearing outfit)
  │
  │  ┌─────────────────────────────────────────────────┐
  ├──│  LLM CALL 1: Classification (Gemini Vision)     │
  │  │  Model: gemini-2.5-flash                        │
  │  │  Input: Full photo + structured prompt           │
  │  │  Output: JSON with items[], each with:           │
  │  │    category, subcategory, color, fabric,         │
  │  │    weather_suitability, style_vibe, suited_for   │
  │  │  Cost: ~2-5s per photo                           │
  │  └─────────────────────────────────────────────────┘
  │                    │
  │          ┌─────────┴─────────┐
  │          │ Per item detected │
  │          └─────────┬─────────┘
  │                    │
  │         ┌──── DEDUP CHECK (Layer 4) ────┐
  │         │ Embed item text → HNSW search │
  │         │ If match < 0.15 → SKIP        │──→ duplicate, stop here
  │         └───────────┬───────────────────┘
  │                     │ (unique item)
  │                     │
  │  ┌─────────────────────────────────────────────────┐
  ├──│  LLM CALL 2: Garment Image Gen (one-shot)       │
  │  │  Model: gemini-2.5-flash-image                  │
  │  │  Input: Full photo + specific item description   │
  │  │  Prompt: "Extract ONLY this specific top:        │
  │  │    dark brown knit V-neck sweater.               │
  │  │    Generate clean product image, white bg,       │
  │  │    no face — like a Zara product page."          │
  │  │  Output: Clean PNG of just that garment          │
  │  │  Cost: ~3-8s per item                            │
  │  └─────────────────────────────────────────────────┘
  │                     │
  │  ┌─────────────────────────────────────────────────┐
  └──│  LLM CALL 3: Text Description + Embedding       │
     │  Step A: Build semantic text from metadata       │
     │    (no LLM — deterministic string concatenation) │
     │  Step B: Embed with all-MiniLM-L6-v2 (384-dim)  │
     │    (local model, ~50ms)                          │
     │  Output: Vector stored in pgvector chunks table  │
     └─────────────────────────────────────────────────┘
```

### LLM Call 1: Classification (Gemini Vision)

The photo is sent to **Gemini 2.5 Flash** with a structured prompt. The prompt specifies exactly what to extract per garment — this is the **richest metadata extraction step**:

| Field | Example | Why it matters |
|-------|---------|----------------|
| `category` | tops, bottoms, dresses, shoes | Slot assignment for outfit assembly |
| `subcategory` | ribbed crew-neck sweater | Specificity for dedup + search |
| `color` | dark brown | Visual identity |
| `fabric` | chunky knit wool | **Key weather signal** — knit = warm, linen = breathable |
| `weather_suitability` | "warm layer for 0-10C" | **Natural language that embeds well** — matches user queries |
| `style_vibe` | cozy-casual | Aesthetic matching |
| `suited_for` | coffee run, everyday | Occasion matching |
| `scene` | park, autumn, casual outing | Where the person was wearing this |

The prompt is structured with rules for each category and explicit instructions for fabric detection ("look at the surface texture: knit/ribbed, smooth cotton, silk/satin, denim...").

### LLM Call 2: Garment Image Generation (One-Shot Prompting)

A **separate Gemini call** using `gemini-2.5-flash-image` (image generation model). The critical detail: the prompt includes the **specific item description from Call 1**:

```
WITHOUT specific description (old, broken):
  "Extract ONLY the top from this photo."
  → Gemini picks randomly when photo has t-shirt + jacket

WITH specific description (current):
  "Extract ONLY this specific top: brown zip-up athletic jacket
   with a high collar, made from synthetic fabric."
  → Gemini targets the exact garment
```

This **one-shot prompt** produces a clean catalog image — white background, no face, no other clothing. The image is saved as PNG and stored as `image_data` (bytea) in Postgres.

### LLM Call 3: Text Description + Semantic Embedding

This is actually **not an LLM call** — it's two deterministic steps:

**Step A: Build semantic text** — concatenate metadata fields into a ~60-word paragraph:

```python
# From dedup.py: build_semantic_text()
"dark brown chunky knit wool V-neck sweater. Thick ribbed texture, cozy.
 Weather: warm insulating layer for cool to cold weather 5-15C.
 Style: cozy-casual. Good for: everyday wear, coffee run.
 Best in fall. Worn at: park, autumn."
```

This text is designed to **embed well** — it contains the exact kind of language users type when asking for outfits ("warm", "casual", "coffee", "5-15C"). The better this text, the better the search quality.

**Step B: Embed with MiniLM** — the semantic text is encoded into a 384-dimensional vector using `all-MiniLM-L6-v2` (runs locally, ~50ms). The vector is stored in pgvector's `chunks` table with `type='wardrobe_item'` and indexed via HNSW for O(1) approximate nearest neighbor search.

### How Text Embeddings Power Both Search AND Dedup

The same embedding serves two purposes:

```
                    semantic_text
                    "dark brown knit sweater..."
                          │
                    ┌─────┴─────┐
                    │  embed()  │  all-MiniLM-L6-v2, 384-dim
                    └─────┬─────┘
                          │
                    384-dim vector
                          │
              ┌───────────┴───────────┐
              │                       │
        DEDUP (at ingestion)    SEARCH (at query time)
              │                       │
     "Does this item already     "What items match
      exist in my wardrobe?"     'party outfit for 12C NYC'?"
              │                       │
     Search chunks WHERE         Search chunks WHERE
     type='wardrobe_item'        type='wardrobe_item'
     max_distance=0.15           max_distance=1.5
              │                       │
     If match found in           Rank by distance +
     same category → SKIP        recency penalty → outfit
```

**Dedup** uses a **tight threshold (0.15)** — items must be ~85% similar to be considered duplicates. This catches "black jersey leggings" ≈ "black slim-fit leggings" but allows "black jersey leggings" ≠ "light blue striped button-up shirt".

**Search** uses a **loose threshold (1.5)** — cast a wide net, then score by distance + recency + style match.

Both use the **same HNSW index** on the same `chunks` table — no separate index or table for dedup.

---

## 4-Layer Deduplication Pipeline

Layers are ordered cheapest → most expensive. Each layer catches what the previous ones missed:

```
Photo arrives in ~/Downloads/wardrobe_inbox/
  │
  ├─ Layer 1: BURST DEDUP ──────────────────── Cost: FREE
  │   Compares timestamps in filenames.
  │   Photos within 300s of each other → keep largest file.
  │   "PXL_20260215_004920750" + "004922213" (2s apart) → skip smaller one.
  │   Catches: rapid shutter, burst mode, similar angles.
  │
  ├─ Layer 2: PERCEPTUAL HASH ─────────────── Cost: ~1ms (local PIL)
  │   Resize to 8x8 grayscale → compute average-hash → hamming distance.
  │   Threshold: ≤ 10 bits difference = duplicate.
  │   Catches: same photo saved with different name, re-exports, screenshots.
  │
  ├─ Layer 3: SOURCE FILE CHECK ───────────── Cost: 1 SQL query
  │   SELECT from wardrobe WHERE source_file = ?
  │   Catches: exact same file dropped in inbox twice.
  │
  │   ── Layers 1-3 run BEFORE any Gemini API call ──
  │   ── Layers below run AFTER Gemini Vision (Call 1) ──
  │
  └─ Layer 4: SEMANTIC DEDUP ──────────────── Cost: ~60ms (embed + HNSW search)
      After Vision extracts items, for EACH item:
        1. Build semantic_text from extracted metadata
        2. Embed with MiniLM (50ms)
        3. Search existing wardrobe_item vectors in same category
        4. If cosine distance < 0.15 → DUPLICATE → skip

      "black jersey leggings" ≈ "black slim-fit leggings" → SKIP
      "black jersey leggings" ≠ "red striped button-up" → ADD

      Runs BEFORE garment image gen (Call 2) — the most expensive step.
      Duplicates never trigger a Gemini image generation call.
```

| Layer | What it catches | Cost | Runs before |
|-------|----------------|------|-------------|
| 1. Burst | Same outfit, rapid shutter | Free | Any API call |
| 2. Hash | Same pixels, different filename | ~1ms | Any API call |
| 3. Source | Same file reprocessed | 1 SQL | Any API call |
| 4. Semantic | Same garment across different photos | ~60ms | Image gen (saves ~5s per dup) |

### Why Layer 4 Matters

Layers 1-3 compare **photos**. Layer 4 compares **garments**.

You might own one pair of black leggings but have 5 photos wearing them at different places. Layers 1-3 won't catch this — different photos, different hashes, different filenames. Layer 4 catches it because the *semantic meaning* of "black stretchy jersey leggings" is nearly identical regardless of which photo it came from.

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
