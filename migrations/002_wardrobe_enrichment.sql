-- Wardrobe enrichment: richer item metadata for semantic outfit recommendation
-- Adds fabric, weather suitability, style, occasion, scene context, and embedding linkage

ALTER TABLE wardrobe ADD COLUMN IF NOT EXISTS fabric TEXT NOT NULL DEFAULT '';
ALTER TABLE wardrobe ADD COLUMN IF NOT EXISTS weather_suitability TEXT NOT NULL DEFAULT '';
ALTER TABLE wardrobe ADD COLUMN IF NOT EXISTS style_vibe TEXT NOT NULL DEFAULT '';
ALTER TABLE wardrobe ADD COLUMN IF NOT EXISTS occasion_context TEXT NOT NULL DEFAULT '';
ALTER TABLE wardrobe ADD COLUMN IF NOT EXISTS photo_scene TEXT NOT NULL DEFAULT '';
ALTER TABLE wardrobe ADD COLUMN IF NOT EXISTS semantic_text TEXT NOT NULL DEFAULT '';

-- Place/activity linked to the item (not stored separately)
ALTER TABLE wardrobe ADD COLUMN IF NOT EXISTS place_type TEXT NOT NULL DEFAULT '';
ALTER TABLE wardrobe ADD COLUMN IF NOT EXISTS place_name TEXT NOT NULL DEFAULT '';
ALTER TABLE wardrobe ADD COLUMN IF NOT EXISTS place_activity TEXT NOT NULL DEFAULT '';
ALTER TABLE wardrobe ADD COLUMN IF NOT EXISTS place_vibe TEXT NOT NULL DEFAULT '';

-- Embedding linkage
ALTER TABLE wardrobe ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMPTZ;
ALTER TABLE wardrobe ADD COLUMN IF NOT EXISTS chunk_id TEXT;
