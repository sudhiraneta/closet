"""Railway startup script — runs before uvicorn starts.

1. Runs schema migration (001_schema.sql)
2. Seeds wardrobe data (002_seed_data.sql) if table is empty
3. Embeds wardrobe items into pgvector if chunks are missing
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.postgres import get_conn

MIGRATIONS = Path(__file__).parent.parent / "migrations"


def run_sql_file(conn, path: Path):
    print(f"Running {path.name}...")
    sql = path.read_text(encoding="utf-8")
    conn.execute(sql)
    conn.commit()
    print(f"  Done.")


def needs_seed(conn) -> bool:
    row = conn.execute("SELECT count(*) as n FROM wardrobe").fetchone()
    return row["n"] == 0


def needs_embedding(conn) -> bool:
    row = conn.execute(
        "SELECT count(*) as n FROM chunks WHERE conversation_id LIKE 'wardrobe_item_%'"
    ).fetchone()
    return row["n"] == 0


def embed_wardrobe(conn):
    from wardrobe.dedup import build_semantic_text
    from memory.vectorstore import VectorStore
    from memory.chunker import Chunk, _ensure_metadata

    items = conn.execute(
        "SELECT id, category, subcategory, color, pattern, season, comfort, "
        "description, semantic_text, fabric, weather_suitability, style_vibe, "
        "occasion_context, suited_for FROM wardrobe"
    ).fetchall()

    print(f"Embedding {len(items)} wardrobe items...")
    # Single VectorStore / model load for all items
    store = VectorStore()

    for item in items:
        item = dict(item)
        pid = item["id"]
        semantic_text = item.get("semantic_text") or build_semantic_text(item)

        chunk = Chunk(
            text=semantic_text,
            metadata=_ensure_metadata({
                "source": "wardrobe",
                "conversation_id": f"wardrobe_item_{pid}",
                "title": f"{item.get('color', '')} {item.get('subcategory', '')}".strip(),
                "type": "wardrobe_item",
                "pillar": "SOCIAL",
                "dimension": "life",
                "classified": "true",
            }),
        )
        store.ingest([chunk])
        chunk_id = store._chunk_id(chunk.text, chunk.metadata)
        conn.execute(
            "UPDATE wardrobe SET chunk_id = %s, embedded_at = NOW() WHERE id = %s",
            (chunk_id, pid),
        )
        conn.commit()
        print(f"  [{pid}] {item['subcategory']}")

    print("Embedding complete.")


def main():
    print("=== Startup ===")

    with get_conn() as conn:
        # 1. Schema
        run_sql_file(conn, MIGRATIONS / "001_schema.sql")

        # 2. Seed data if empty
        if needs_seed(conn):
            seed_file = MIGRATIONS / "002_seed_data.sql"
            if seed_file.exists():
                run_sql_file(conn, seed_file)
                print("Wardrobe data seeded.")
            else:
                print("No seed file found — wardrobe will be empty.")
        else:
            print("Wardrobe already has data, skipping seed.")

        # 3. Embed if chunks missing
        if needs_embedding(conn):
            print("No wardrobe embeddings found, generating...")
            embed_wardrobe(conn)
        else:
            print("Wardrobe embeddings already present.")

    print("=== Startup complete ===\n")


if __name__ == "__main__":
    main()
