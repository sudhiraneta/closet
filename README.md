# Closet

AI-powered wardrobe manager and outfit recommender. Drop photos of your outfits, get a smart closet that recommends what to wear based on weather, occasion, and style.

## How it works

1. **Drop photos** in `~/Downloads/wardrobe_inbox/` or upload via the UI
2. **Gemini Vision** analyzes each photo — identifies clothing items, fabric, color, weather suitability, style
3. **Garment images** are generated as clean catalog-style product shots (Zara-style, white background)
4. **Semantic embeddings** are created for each item so the closet understands what goes with what
5. **Ask for an outfit** in natural language — "party outfit for NYC tonight" — and get a recommendation via semantic search, no LLM needed

## Features

- **Smart dedup** — 4-layer pipeline prevents duplicate items (burst photos, perceptual hash, source file check, semantic similarity)
- **Semantic outfit search** — your prompt + real-time weather → vector search against your wardrobe embeddings → outfit in ~60ms
- **Enriched metadata** — fabric, texture, weather range (Celsius), style vibe, occasion — all extracted from the source photo
- **Recency tracking** — won't suggest the same outfit twice in a week

## Setup

Shared with [ai-twin](https://github.com/sudhiraneta/ai-twin) infrastructure:

```bash
# Requires ai-twin's Postgres (port 5433), pgvector, and embedding engine
# Run migration
psql -p 5433 ai_twin -f migrations/002_wardrobe_enrichment.sql

# The wardrobe package is imported by ai-twin's main.py and ui/app.py
```

## Project Structure

```
closet/
├── wardrobe/
│   ├── __init__.py     # Package exports
│   ├── vision.py       # Gemini Vision analysis + garment image generation
│   ├── dedup.py        # 4-layer deduplication (burst, hash, source, semantic)
│   ├── store.py        # Postgres save + pgvector embedding
│   ├── builder.py      # Photo processing pipeline (process_inbox_photos)
│   ├── outfit.py       # Outfit recommendation (semantic search, no LLM)
│   ├── routes.py       # FastAPI endpoints (/wardrobe/*)
│   └── page.py         # Streamlit UI (Closet, Outfit, Add New tabs)
├── migrations/
│   └── 002_wardrobe_enrichment.sql
└── README.md
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/wardrobe/items` | GET | List all wardrobe items |
| `/wardrobe/image/{id}` | GET | Serve garment image |
| `/wardrobe/outfit?prompt=...` | POST | Get outfit recommendation from natural language |
| `/wardrobe/inbox` | POST | Process photos in inbox folder |
| `/wardrobe/items/add` | POST | Upload a single photo |
| `/wardrobe/reprocess` | POST | Re-analyze all items with enriched Vision prompt |
