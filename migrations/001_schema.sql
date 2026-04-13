-- Closet schema — creates all tables needed for the wardrobe app.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    embedding vector(384),
    source TEXT DEFAULT '',
    conversation_id TEXT DEFAULT '',
    title TEXT DEFAULT '',
    timestamp TIMESTAMPTZ,
    msg_timestamp TIMESTAMPTZ,
    role TEXT DEFAULT '',
    type TEXT DEFAULT '',
    pillar TEXT DEFAULT '',
    dimension TEXT DEFAULT '',
    classified BOOLEAN DEFAULT FALSE,
    cluster_id TEXT DEFAULT '',
    cluster_label TEXT DEFAULT '',
    extra JSONB DEFAULT '{}',
    content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_chunks_content_tsv ON chunks USING gin (content_tsv);
CREATE INDEX IF NOT EXISTS idx_chunks_type ON chunks (type);

CREATE TABLE IF NOT EXISTS wardrobe (
    id SERIAL PRIMARY KEY,
    item_name TEXT DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    subcategory TEXT DEFAULT '',
    color TEXT DEFAULT '',
    pattern TEXT DEFAULT 'solid',
    season TEXT DEFAULT 'all_season',
    comfort TEXT DEFAULT 'casual',
    style_tags JSONB DEFAULT '[]',
    suited_for TEXT DEFAULT '',
    source_file TEXT DEFAULT '',
    description TEXT DEFAULT '',
    fabric TEXT DEFAULT '',
    weather_suitability TEXT DEFAULT '',
    style_vibe TEXT DEFAULT '',
    occasion_context TEXT DEFAULT '',
    photo_scene TEXT DEFAULT '',
    place_type TEXT DEFAULT '',
    place_name TEXT DEFAULT '',
    place_activity TEXT DEFAULT '',
    place_vibe TEXT DEFAULT '',
    semantic_text TEXT DEFAULT '',
    image_data BYTEA,
    image_mime TEXT,
    source_photo TEXT DEFAULT '',
    embedded_at TIMESTAMPTZ,
    chunk_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS outfit_history (
    id SERIAL PRIMARY KEY,
    top_id INTEGER REFERENCES wardrobe(id),
    bottom_id INTEGER REFERENCES wardrobe(id),
    dress_id INTEGER REFERENCES wardrobe(id),
    shoes_id INTEGER REFERENCES wardrobe(id),
    weather_temp FLOAT,
    weather_condition TEXT DEFAULT '',
    style TEXT DEFAULT '',
    reasoning TEXT DEFAULT '',
    city TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
