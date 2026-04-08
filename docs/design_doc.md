# Digital Closet: System Design Document

**Author:** Sudhir Abadugu  
**Status:** Implemented  
**Last Updated:** 2026-04-08

---

## 1. Problem Statement

People own 60-100 garments on average but wear roughly 20% of them regularly. The core failure mode is cognitive: standing in front of a closet, you can't reason about weather appropriateness, pattern clashing, outfit staleness, and occasion fit simultaneously. Existing solutions (Cladwell, Stylebook) require manual data entry per garment — category, color, season, fabric — which creates enough friction that adoption collapses within weeks.

This system eliminates manual cataloging entirely. Drop a photo (selfie, mirror shot, group photo), and the pipeline extracts individual garments, classifies their attributes, generates clean catalog images, and embeds them into a vector space purpose-built for natural-language outfit queries. A conversational agent then reasons over the catalog in real time, factoring in live weather, recent wear history, and user-stated occasion to compose outfits from what you actually own.

## 2. Goals and Non-Goals

### Goals

- **Zero-friction ingestion.** A photo dropped into an inbox folder should reach the catalog with no user interaction beyond the drop.
- **Weather-aware recommendations.** Outfit suggestions must reflect current conditions at the user's stated location, not generic seasonal labels.
- **Outfit diversity.** The system should actively avoid recommending the same items repeatedly across a rolling window.
- **Pattern coherence.** Outfits must not contain clashing patterns (e.g., striped top + plaid bottom).
- **Conversational refinement.** Users should be able to say "that top is in the laundry" or "something more casual" and get an updated recommendation without restarting.

### Non-Goals

- **Outfit generation from external catalogs.** We only recommend from items the user owns.
- **Purchase recommendations.** No affiliate links, no "you should buy this."
- **Social/sharing features.** This is a single-user tool.
- **Fit or sizing.** We classify style, not body measurements.
- **Real-time photo stream.** Ingestion is batch, not live-camera.

## 3. Architecture Overview

The system is two decoupled lanes that share a persistence layer but never call each other at runtime.

```
                        INGESTION (offline, batch)
                        ─────────────────────────

  ~/Downloads/wardrobe_inbox/
         │
         ▼
  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
  │ Burst Dedup  │ ──▶ │ Perceptual   │ ──▶ │ Source File  │
  │ (timestamp)  │     │ Hash (aHash) │     │ Check (SQL)  │
  └──────────────┘     └──────────────┘     └──────────────┘
         │                                         │
         │              3 cheap layers before       │
         │              any API call                │
         ▼                                         ▼
  ┌──────────────┐                          ┌──────────────┐
  │ Gemini Flash │ ◀────────────────────────│ Surviving    │
  │ Vision       │   classify scene +       │ Photos       │
  │ (classify)   │   per-item attributes    └──────────────┘
  └──────────────┘
         │
         ▼
  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
  │ Semantic     │ ──▶ │ Gemini Flash │ ──▶ │ Postgres +   │
  │ Dedup        │     │ Image Gen    │     │ pgvector     │
  │ (vector,     │     │ (clean       │     │ (save +      │
  │  d < 0.15)   │     │  catalog img)│     │  embed)      │
  └──────────────┘     └──────────────┘     └──────────────┘
         │
         │  Layer 4 sits AFTER classification
         │  (needs attributes) but BEFORE image gen
         │  (the most expensive call)
         ▼

═══════════════════════════════════════════════════════════════
                    Postgres + pgvector
                    wardrobe table (structured)
                    chunks table (vector embeddings)
═══════════════════════════════════════════════════════════════

         ▲
         │
         │
  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
  │ City →       │ ──▶ │ HNSW Vector  │ ──▶ │ Scoring:     │
  │ Geocode →    │     │ Search       │     │ distance +   │
  │ Weather      │     │ (d < 1.5,    │     │ recency      │
  │ (Open-Meteo) │     │  top 30)     │     │ penalty      │
  └──────────────┘     └──────────────┘     └──────────────┘
                                                   │
                                                   ▼
                                            ┌──────────────┐
                                            │ Compose:     │
                                            │ dress vs     │
                                            │ top+bottom,  │
                                            │ pattern      │
                                            │ clash check  │
                                            └──────────────┘

                        RECOMMENDATION (online, per-request)
                        ────────────────────────────────────
```

**Why two lanes?** Ingestion is I/O- and cost-heavy (vision API calls, image generation). Recommendation must be fast (<2s). Decoupling means ingestion failures never block outfit queries, and the recommendation path touches only local compute (embedding) + Postgres (HNSW index scan). The only shared contract is the `semantic_text` field and its embedding in the `chunks` table.

## 4. Detailed Design

### 4.1 Ingestion Pipeline

#### Entry Point

`builder.process_inbox_photos()` scans `~/Downloads/wardrobe_inbox/` for image files (`.jpg`, `.jpeg`, `.png`, `.heic`, `.webp`). This is designed to be run on-demand or via cron — there is no file watcher.

#### Deduplication (4 Layers)

The dedup strategy is layered by cost. Each layer is progressively more expensive but catches a different class of duplicate.

| Layer | What it catches | Cost | Runs before API? |
|-------|----------------|------|-------------------|
| **1. Burst grouping** | Multiple shots from the same moment (phone burst mode). Groups photos by parsed EXIF timestamp within a 300s window; keeps the largest file. | O(n log n) sort | Yes |
| **2. Perceptual hash** | Same photo at different resolutions or with minor crops. 8x8 grayscale average hash, Hamming distance threshold of 10 bits. | O(n) per photo, ~1ms each | Yes |
| **3. Source file check** | Re-processing the same file. SQL `SELECT DISTINCT source_file FROM wardrobe`. | One DB round-trip | Yes |
| **4. Semantic dedup** | Different photos of the same garment (e.g., same shirt photographed on two different days). Embeds the classified attributes and searches existing vectors with distance < 0.15, filtered to same category. | Embedding + HNSW search | After Vision, before Image Gen |

The critical design decision is where Layer 4 sits. It needs the Vision classification output (category, color, fabric) to build the semantic text, so it must run after the Gemini Vision call. But it runs *before* the Gemini Image Generation call, which is the most expensive operation (~5x the cost of classification). This ordering means we pay for classification on a duplicate but never pay for image generation on one.

**Threshold derivation.** The 0.15 semantic dedup threshold was empirically derived from pairwise distances across the catalog. The observed distribution shows a gap between 0.10 (true duplicates — same garment, different photo) and 0.22 (genuinely different items of similar style). The threshold sits in the middle of this gap.

#### Vision Classification

`vision.analyze_photo()` sends each photo to Gemini 2.5 Flash with a structured prompt requesting per-item extraction. The prompt specifies the exact JSON schema and instructs the model to identify all distinct garments visible in the scene.

Extracted per item:
- `category`: top, bottom, dress, shoes (closed enum)
- `subcategory`: e.g., "henley," "chinos," "chelsea boots"
- `color`, `pattern`, `fabric`
- `weather_suitability`: natural language with Celsius ranges (e.g., "Suitable for cool weather, 10-18C, light layering")
- `style_vibe`, `occasion`

Extracted per scene:
- `location_type`, `landmark`, `activity`, `vibe`

Scene context flows into the semantic text so that "the jacket I wore at that rooftop bar" can match at query time.

#### Garment Image Generation

`vision.extract_garment_image()` uses Gemini 2.5 Flash (image generation mode) to produce a clean, white-background, Zara-catalog-style product image of each detected garment. The prompt explicitly instructs: no face, no person, no mannequin — just the garment. Output is 400x400 PNG, stored as `bytea` in Postgres.

This is the most expensive step per item and the primary reason dedup is so aggressive.

#### Semantic Text Construction

`dedup.build_semantic_text()` is the bridge between structured metadata and the vector space. It converts classified attributes into a natural-language paragraph optimized for embedding similarity with the kinds of queries users actually ask:

```
navy blue cotton henley with subtle texture.
Weather: Suitable for cool to mild weather, 12-22C.
Style: casual relaxed weekend. Occasion: coffee, errands, casual meetups.
Season: spring, fall.
Photographed at: rooftop bar, social gathering, relaxed evening vibe.
```

This construction is intentional — users don't query "subcategory=henley AND color=navy." They ask "something warm and casual for a coffee date when it's 15 degrees." The semantic text is shaped to match that query distribution.

#### Persistence

Each garment gets two representations in the database:

1. **Structured row** in `wardrobe` table (24 columns) — for filtering, display, and the image blob.
2. **Vector embedding** in `chunks` table (384-dim, all-MiniLM-L6-v2) — for semantic search.

These are linked by `chunk_id` on the wardrobe row and `conversation_id = wardrobe_item_{id}` on the chunk. This bidirectional link allows the recommendation engine to search vectors, then hydrate full garment metadata from the structured table.

### 4.2 Recommendation Engine

Two interfaces serve the same core logic:

- **`outfit.generate_outfit()`** — stateless, single-shot API endpoint.
- **`agent.agent_step()`** — stateful, multi-turn conversational agent.

#### Query Pipeline

1. **City extraction.** Regex parser for `"in <City>"` patterns plus a hardcoded abbreviation map (NYC, SF, LA, DC, CHI). Falls back to San Francisco.
2. **Geocoding.** Open-Meteo geocoding API (free, no key required).
3. **Weather fetch.** Open-Meteo forecast API. Returns temperature (C/F), humidity, wind speed, and WMO-coded condition mapped to human-readable text.
4. **Query augmentation.** The user prompt is concatenated with weather context. If conditions include rain, the system appends "rain resistant closed shoes" to bias the vector search toward appropriate footwear.
5. **Vector search.** HNSW index scan against `chunks` table, filtered to `type = wardrobe_item`, returning top 30 results within distance 1.5.
6. **Scoring.** Each result is scored as `distance + recency_penalty`, where recency comes from the `outfit_history` table:

| Last recommended | Penalty |
|-----------------|---------|
| Today | +10.0 |
| Yesterday | +0.5 |
| 2 days ago | +0.2 |
| 3+ days ago | 0.0 |

7. **Category grouping.** Results are bucketed into tops, bottoms, dresses, shoes.
8. **Dress vs. separates decision.** If the best-scoring dress beats the average of the best top + best bottom, select the dress. Otherwise, select top + bottom.
9. **Pattern clash prevention.** If both the selected top and bottom have non-solid patterns, the bottom is swapped for the next-best solid-pattern alternative in the same category.
10. **History logging.** The recommended outfit is written to `outfit_history` for future recency penalties.

#### The Threshold Asymmetry

The same HNSW index and embedding space serves both ingestion and recommendation, but with radically different distance thresholds:

- **Dedup (ingestion):** distance < **0.15** — extremely tight, only true duplicates pass.
- **Search (recommendation):** distance < **1.5** — intentionally broad, casting a wide net.

This asymmetry is correct. Dedup needs precision (false positives mean lost garments). Search needs recall (false negatives mean missed outfit options). The scoring layer after search handles ranking; the distance threshold just sets the candidate pool size.

### 4.3 Conversational Agent

`agent.py` implements a state machine with explicit transitions:

```
start ──▶ city ──▶ style ──▶ recommend ──▶ laundry ──▶ done
                                │              │
                                │              ▼
                                │         pick_laundry
                                │              │
                                ◀──────────────┘
                                     (re-recommend)
```

**Session state** (`OutfitSession` dataclass):
- `city`, `weather` — resolved once, reused across turns.
- `style`, `occasion` — can be updated mid-conversation ("actually, something more formal").
- `excluded_ids` — items the user has marked as in the laundry or otherwise unavailable.
- `suggested_ids` — items already shown, penalized (+5.0) but not excluded.
- `current_outfit` — the most recent recommendation, for reference in follow-ups.

The agent attempts to short-circuit the state machine: if the initial prompt contains both a city and style cue ("casual outfit for NYC"), it skips directly to recommendation. This avoids the annoying multi-turn interrogation that plagues most conversational systems.

**Laundry loop.** When the user says "that top is in the laundry," the agent:
1. Identifies which item(s) the user is referring to.
2. Adds them to `excluded_ids`.
3. Re-runs recommendation with the updated exclusion set.
4. The excluded item will never appear in this session again.

This is a simple but important UX detail — laundry is the #1 reason an outfit suggestion fails in practice.

### 4.4 Data Model

#### `wardrobe` Table

```sql
CREATE TABLE wardrobe (
    id              SERIAL PRIMARY KEY,
    category        TEXT NOT NULL,        -- top, bottom, dress, shoes
    subcategory     TEXT,                 -- henley, chinos, chelsea boots, etc.
    color           TEXT,
    pattern         TEXT,                 -- solid, striped, plaid, etc.
    season          TEXT,
    comfort         TEXT,
    style_tags      JSONB,
    suited_for      TEXT,
    description     TEXT,
    item_name       TEXT,
    fabric          TEXT,                 -- cotton, wool, polyester blend, etc.
    weather_suitability TEXT,             -- natural language with Celsius ranges
    style_vibe      TEXT,                 -- casual relaxed, smart casual, formal, etc.
    occasion_context TEXT,               -- coffee, office, dinner, etc.
    photo_scene     TEXT,                 -- raw scene context from Vision
    place_type      TEXT,                 -- rooftop bar, office, park, etc.
    place_name      TEXT,
    place_activity  TEXT,
    place_vibe      TEXT,
    semantic_text   TEXT,                 -- the full embedding source text
    image_data      BYTEA,               -- 400x400 PNG, clean catalog image
    image_mime      TEXT,                 -- image/png
    source_photo    TEXT,                 -- path to original photo
    source_file     TEXT,                 -- original filename (for dedup layer 3)
    chunk_id        TEXT,                 -- FK to chunks table
    embedded_at     TIMESTAMPTZ
);
```

#### `chunks` Table (Vector Store)

Wardrobe items are embedded alongside all other AI Twin documents. They are distinguished by metadata:
- `type = 'wardrobe_item'`
- `conversation_id = 'wardrobe_item_{id}'`
- `dimension = 'life'`
- `pillar = 'SOCIAL'`

This colocation means wardrobe items participate in the broader AI Twin RAG pipeline. A question like "what was I wearing when I went to that conference?" can surface wardrobe chunks alongside conversation and notes chunks.

#### `outfit_history` Table

```sql
CREATE TABLE outfit_history (
    id          SERIAL PRIMARY KEY,
    item_ids    INTEGER[],           -- array of wardrobe item IDs
    prompt      TEXT,
    weather     JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

### 4.5 API Surface

Six endpoints, all under `/wardrobe`:

| Method | Path | Purpose | Latency |
|--------|------|---------|---------|
| `GET` | `/wardrobe/items` | List catalog, optional `?category=` filter | <100ms |
| `GET` | `/wardrobe/image/{item_id}` | Serve garment image bytes | <50ms |
| `POST` | `/wardrobe/outfit?prompt=` | Single-shot outfit recommendation | 1-3s |
| `POST` | `/wardrobe/inbox` | Trigger inbox processing pipeline | 30s-5min |
| `POST` | `/wardrobe/items/add` | Upload single photo via multipart form | 10-30s |
| `POST` | `/wardrobe/reprocess` | Re-analyze all existing items | Minutes |

### 4.6 UI

Streamlit app with three tabs:

- **Closet** — Filterable grid (4 columns) of all garments with catalog images, subcategory labels, color, and season. Category radio filter + stats bar.
- **Outfit** — Text prompt input, weather banner (dark gradient showing temp/conditions), reasoning explanation, and outfit grid with garment images.
- **Add New** — Single photo upload or batch inbox trigger.

## 5. Key Trade-offs

### Gemini for both classification and image generation

**Choice:** Use Gemini 2.5 Flash for vision classification and Gemini 2.5 Flash (image mode) for catalog image generation.

**Alternative considered:** Use a local model (e.g., CLIP + stable diffusion inpainting) for garment extraction.

**Rationale:** Gemini Flash is fast and cheap enough that the API cost per garment ($0.001-0.005) is negligible compared to the engineering cost of running local generation models. The quality gap is substantial — Gemini produces clean, consistent catalog images that a local pipeline would struggle to match without significant tuning. The trade-off is API dependency, but garment ingestion is infrequent (a few items per week) so availability risk is low.

### Semantic text as the embedding source, not raw images

**Choice:** Embed a natural-language description of the garment, not the garment image itself.

**Alternative considered:** Use CLIP or a vision-language model to embed the garment image directly into a shared text-image space.

**Rationale:** User queries are text. The retrieval problem is text-to-text, not text-to-image. By converting garment attributes into natural language shaped like the queries users ask ("warm casual jacket for 15C rainy day"), we get better retrieval relevance than we would from cross-modal embeddings. The classification step (Vision API) does the hard work of extracting structured attributes; the semantic text construction step shapes those attributes for retrieval. This separation of concerns means we can tune the semantic text template without re-running Vision.

### Recency penalty in scoring, not hard exclusion

**Choice:** Recently recommended items get a distance penalty (+0.2 to +10.0), not a hard filter.

**Alternative considered:** Exclude items recommended in the last N days entirely.

**Rationale:** Hard exclusion breaks down for small wardrobes. If you own 3 pairs of shoes and exclude 2, you're stuck with the third regardless of weather/style fit. A penalty system degrades gracefully — recently worn items *can* still be selected if they're the clearly best match, but the system will prefer alternatives when they exist.

### Images stored as BYTEA in Postgres, not on filesystem

**Choice:** Store the 400x400 PNG catalog images directly in the `wardrobe` table as `bytea`.

**Alternative considered:** Store on filesystem with a path reference, or in object storage (S3).

**Rationale:** Single-user system with ~100-300 garments. At 400x400 PNG, each image is 50-150KB. Total storage is 15-45MB — negligible for Postgres. Storing in-database eliminates file path management, backup complexity, and orphaned file risks. The `/wardrobe/image/{item_id}` endpoint streams directly from the query result. This would not scale to a multi-user SaaS product, but it's the right call for a personal tool.

### Open-Meteo over OpenWeatherMap

**Choice:** Open-Meteo for weather and geocoding.

**Alternative considered:** OpenWeatherMap (more common), WeatherAPI, etc.

**Rationale:** Open-Meteo is completely free with no API key required. For a personal tool where weather is a supporting input (not the core product), paying for or managing API keys for weather data is unnecessary overhead. Accuracy is sufficient for outfit-level decisions (you don't need 0.1C precision to decide between a jacket and a t-shirt).

## 6. Operational Concerns

### Cost Model

| Operation | Provider | Cost per call | Frequency |
|-----------|----------|--------------|-----------|
| Vision classification | Gemini 2.5 Flash | ~$0.001 | Per photo ingested |
| Image generation | Gemini 2.5 Flash (image) | ~$0.005 | Per garment extracted |
| Embedding | Local (MiniLM) | $0 | Per garment + per query |
| Weather | Open-Meteo | $0 | Per outfit request |
| Vector search | Postgres HNSW | $0 | Per outfit request |

At typical usage (2-5 garments/week, 1-3 outfit queries/day), monthly API cost is under $0.50.

### Failure Modes

| Failure | Impact | Mitigation |
|---------|--------|------------|
| Gemini API down | Ingestion blocked, outfits still work | Ingestion is batch/async; retry later |
| Vision misclassifies | Wrong category/attributes, bad search | Semantic dedup may catch; user can reprocess |
| Weather API down | No weather context in query | Hardcoded fallback to San Francisco defaults |
| Postgres down | Everything broken | Standard Postgres HA practices |
| Duplicate garment ingested | Redundant entries in search results | 4-layer dedup; can reprocess to clean up |
| Image gen produces bad image | Poor catalog visual | Cosmetic only; search uses text, not image |

### Capacity

Current schema comfortably handles wardrobes up to ~1,000 items. HNSW index performance remains sub-10ms for catalogs of this size. The practical bottleneck is Gemini API rate limits during bulk ingestion, not storage or search performance.

## 7. Future Considerations

These are directions the architecture naturally supports but are explicitly **not** in the current scope:

- **Wear tracking via photo recognition.** If the system could identify what you're wearing from a daily selfie, recency penalties could reflect actual wear instead of recommendation history.
- **Seasonal rotation.** Auto-suggesting items to pack away or bring out based on shifting weather patterns.
- **Outfit rating feedback loop.** Let users rate recommended outfits; use ratings to fine-tune the scoring weights.
- **Multi-user.** Would require tenant isolation, object storage for images, and auth. Significant rearchitecture.
- **Color harmony scoring.** Beyond pattern clash prevention — consider complementary/analogous color relationships in outfit composition.

## 8. Appendix: Module Dependency Graph

```
wardrobe/
├── builder.py ──▶ vision.py (classify, image gen)
│              ──▶ dedup.py (all 4 layers)
│              ──▶ store.py (save, embed)
│
├── outfit.py  ──▶ vision.py (weather only)
│              ──▶ store.py (search, hydrate)
│
├── agent.py   ──▶ outfit.py (shared scoring logic)
│              ──▶ vision.py (weather)
│
├── routes.py  ──▶ builder.py, outfit.py, agent.py, store.py
│
├── page.py    ──▶ routes.py (via HTTP)
│
└── store.py   ──▶ ai-twin/db/postgres.py (connection pool)
               ──▶ ai-twin/memory/vectorstore.py (embedding + HNSW)
```

External dependencies: `google.genai` (Gemini), `sentence-transformers` (MiniLM), `psycopg` (Postgres), `httpx` (weather/geocoding), `PIL` (image processing).
