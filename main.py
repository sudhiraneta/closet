import os
import sys
from pathlib import Path

CLOSET_ROOT = str(Path(__file__).parent)
sys.path.insert(0, CLOSET_ROOT)

# Set PYTHONPATH so uvicorn's reloader subprocess inherits the path
existing = os.environ.get("PYTHONPATH", "")
if CLOSET_ROOT not in existing:
    os.environ["PYTHONPATH"] = f"{CLOSET_ROOT}:{existing}" if existing else CLOSET_ROOT

from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from wardrobe.routes import router as wardrobe_router


def _run_startup():
    """Schema migration + seeding — runs after uvicorn is up."""
    from pathlib import Path as _Path
    from db.postgres import get_conn

    migrations = _Path(__file__).parent / "migrations"

    def _sql(conn, path):
        print(f"[startup] Running {path.name}...")
        conn.execute(path.read_text(encoding="utf-8"))
        conn.commit()
        print(f"[startup]   Done.")

    try:
        with get_conn() as conn:
            # 1. Schema
            _sql(conn, migrations / "001_schema.sql")

            # 2. Seed wardrobe if empty
            n = conn.execute("SELECT count(*) as n FROM wardrobe").fetchone()["n"]
            if n == 0:
                seed = migrations / "002_seed_data.sql"
                if seed.exists():
                    _sql(conn, seed)
                    print("[startup] Wardrobe seeded.")
                else:
                    print("[startup] No seed file found.")
            else:
                print(f"[startup] Wardrobe already has {n} items, skipping seed.")

            # 3. Embed if chunks missing
            nc = conn.execute(
                "SELECT count(*) as n FROM chunks WHERE conversation_id LIKE 'wardrobe_item_%'"
            ).fetchone()["n"]
            if nc == 0:
                print("[startup] No embeddings found, generating...")
                _embed_wardrobe(conn)
            else:
                print(f"[startup] {nc} wardrobe embeddings present.")

        print("[startup] Complete.")
    except Exception as exc:
        print(f"[startup] ERROR — DB not ready or seed failed: {exc}")
        print("[startup] App will still serve. Re-deploy or check DATABASE_URL.")


def _embed_wardrobe(conn):
    from wardrobe.dedup import build_semantic_text
    from memory.vectorstore import VectorStore
    from memory.chunker import Chunk, _ensure_metadata

    items = conn.execute(
        "SELECT id, category, subcategory, color, pattern, season, comfort, "
        "description, semantic_text, fabric, weather_suitability, style_vibe, "
        "occasion_context, suited_for FROM wardrobe"
    ).fetchall()

    store = VectorStore()
    for item in items:
        item = dict(item)
        pid = item["id"]
        text = item.get("semantic_text") or build_semantic_text(item)
        chunk = Chunk(
            text=text,
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
        print(f"[startup]   embedded [{pid}] {item['subcategory']}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import threading
    t = threading.Thread(target=_run_startup, daemon=True)
    t.start()
    yield


app = FastAPI(
    title="Closet",
    description="AI-powered wardrobe manager and outfit recommender.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(wardrobe_router, prefix="/api")


@app.get("/")
def root():
    return {"name": "Closet", "status": "running", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
