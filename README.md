# Closet

A tool-using **ReAct-style agent** sitting on top of a **batch ETL/indexing pipeline** for wardrobe management and outfit recommendation.

The recommender is a **single-agent orchestrator with tool calls** — not multi-agent. One brain that plans, calls tools (`ask_user`, `get_weather`, `query_closet`), reasons, and outputs. The pipeline beneath it handles photo ingestion, garment extraction, deduplication, and semantic indexing.

## Architecture

```
                         USER
                          |
                    [Natural Language]
                    "Party outfit for NYC tonight"
                          |
                    +-----------+
                    |   AGENT   |  ReAct loop (reason → act → observe)
                    |  agent.py |
                    +-----------+
                     |    |    |
            +--------+    |    +--------+
            |             |             |
      ask_user()    get_weather()  query_closet()
      (city, style,  (Open-Meteo)   (pgvector
       laundry)                      semantic search)
                                        |
                               +--------+--------+
                               |                  |
                         wardrobe table      chunks table
                         (Postgres)         (pgvector embeddings)
                               |
                    +----------+----------+
                    |                     |
              Batch ETL Pipeline     Garment Images
              (process_inbox_photos)  (Gemini Image Gen)
                    |
            +-------+-------+-------+
            |       |       |       |
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

## How the Agent Works

The agent (`wardrobe/agent.py`) follows a ReAct pattern with session state:

```
Turn 1: "I am in NYC for my bday, party outfit please"
  [Reason]  City = NYC, occasion = party. Need weather.
  [Act]     get_weather("NYC") → 12C, partly cloudy
  [Act]     query_closet(style="party", weather=12C) → dress + boots
  [Observe] Outfit ready.
  → "Here's what I'd recommend for NYC (12C, partly cloudy):"
  → Shows: midi sundress + ankle boots
  → "Is anything in the laundry?"

Turn 2: "The sundress is in the laundry"
  [Reason]  Exclude sundress (id:177) for this session.
  [Act]     query_closet(exclude=[177]) → different dress + sneakers
  [Observe] New outfit, no sundress.
  → "Got it — here's an updated outfit:"
  → Shows: wrap dress + chunky sneakers

Turn 3: "Looks good!"
  → "You're all set! Have a great day."
  → Session ends. Laundry exclusions are forgotten.
```

**Session state** (lives in memory, not persisted):
- City + weather (fetched once per session)
- Style/occasion preferences
- Excluded IDs (laundry — session-only, not permanent)
- Suggested IDs (everything recommended this session — avoided in re-rolls)

**Tools the agent calls:**
| Tool | Purpose |
|------|---------|
| `tool_get_weather(city)` | Geocode city → fetch real-time weather from Open-Meteo |
| `tool_query_closet(session)` | Semantic search against wardrobe embeddings, filtered by exclusions |
| `tool_exclude_laundry(ids)` | Mark items as excluded for this session only |

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
