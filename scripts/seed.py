"""Seed remote Closet database from local data.

Usage:
    python scripts/seed.py <REMOTE_DATABASE_URL>

Copies wardrobe items (with images) and their chunk embeddings from
the local Postgres to a remote database. Run once after first deploy.

Railway DB URL (find it in Railway dashboard → Postgres plugin → Variables):
    postgresql://postgres:password@host.railway.app:5432/railway
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psycopg import connect
from psycopg.rows import dict_row

LOCAL_DB = "postgresql://sudhirabadugu@localhost:5433/ai_twin"


def run_schema(remote_url: str):
    """Run the schema migration on the remote DB."""
    schema_file = Path(__file__).parent.parent / "migrations" / "001_schema.sql"
    sql = schema_file.read_text()
    with connect(remote_url) as conn:
        conn.execute(sql)
        conn.commit()
    print("Schema created.")


def seed_wardrobe(remote_url: str):
    """Copy wardrobe rows (including image BYTEA) from local to remote."""
    with connect(LOCAL_DB, row_factory=dict_row) as local:
        rows = local.execute(
            "SELECT id, item_name, category, subcategory, color, pattern, season, "
            "comfort, style_tags, suited_for, source_file, description, "
            "fabric, weather_suitability, style_vibe, occasion_context, photo_scene, "
            "place_type, place_name, place_activity, place_vibe, semantic_text, "
            "image_data, image_mime, source_photo, embedded_at, chunk_id "
            "FROM wardrobe ORDER BY id"
        ).fetchall()

    print(f"Found {len(rows)} wardrobe items locally.")

    with connect(remote_url) as remote:
        for r in rows:
            remote.execute(
                """INSERT INTO wardrobe (
                    id, item_name, category, subcategory, color, pattern, season,
                    comfort, style_tags, suited_for, source_file, description,
                    fabric, weather_suitability, style_vibe, occasion_context, photo_scene,
                    place_type, place_name, place_activity, place_vibe, semantic_text,
                    image_data, image_mime, source_photo, embedded_at, chunk_id
                ) VALUES (
                    %(id)s, %(item_name)s, %(category)s, %(subcategory)s, %(color)s,
                    %(pattern)s, %(season)s, %(comfort)s, %(style_tags)s, %(suited_for)s,
                    %(source_file)s, %(description)s, %(fabric)s, %(weather_suitability)s,
                    %(style_vibe)s, %(occasion_context)s, %(photo_scene)s,
                    %(place_type)s, %(place_name)s, %(place_activity)s, %(place_vibe)s,
                    %(semantic_text)s, %(image_data)s, %(image_mime)s, %(source_photo)s,
                    %(embedded_at)s, %(chunk_id)s
                ) ON CONFLICT (id) DO NOTHING""",
                dict(r),
            )
        # Reset the serial sequence to avoid conflicts on future inserts
        remote.execute("SELECT setval('wardrobe_id_seq', (SELECT COALESCE(MAX(id), 0) FROM wardrobe))")
        remote.commit()

    print(f"Seeded {len(rows)} wardrobe items.")


def seed_chunks(remote_url: str):
    """Copy wardrobe-related chunks (embeddings) from local to remote."""
    with connect(LOCAL_DB, row_factory=dict_row) as local:
        rows = local.execute(
            "SELECT id, content, embedding::text as embedding, "
            "source, conversation_id, title, timestamp, msg_timestamp, "
            "role, type, pillar, dimension, classified, "
            "cluster_id, cluster_label, extra "
            "FROM chunks WHERE type = 'wardrobe_item' ORDER BY id"
        ).fetchall()

    print(f"Found {len(rows)} wardrobe chunks locally.")

    with connect(remote_url) as remote:
        for r in rows:
            remote.execute(
                """INSERT INTO chunks (
                    id, content, embedding,
                    source, conversation_id, title, timestamp, msg_timestamp,
                    role, type, pillar, dimension, classified,
                    cluster_id, cluster_label, extra
                ) VALUES (
                    %(id)s, %(content)s, %(embedding)s::vector,
                    %(source)s, %(conversation_id)s, %(title)s, %(timestamp)s,
                    %(msg_timestamp)s, %(role)s, %(type)s, %(pillar)s,
                    %(dimension)s, %(classified)s, %(cluster_id)s,
                    %(cluster_label)s, %(extra)s::jsonb
                ) ON CONFLICT (id) DO NOTHING""",
                dict(r),
            )
        remote.commit()

    print(f"Seeded {len(rows)} chunks.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/seed.py <REMOTE_DATABASE_URL>")
        print("  e.g. python scripts/seed.py 'postgres://user:pass@host.render.com:5432/closet?sslmode=require'")
        sys.exit(1)

    remote_url = sys.argv[1]
    print(f"Seeding remote DB...")
    run_schema(remote_url)
    seed_wardrobe(remote_url)
    seed_chunks(remote_url)
    print("Done! Your closet is live.")
