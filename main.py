import os
import sys
from pathlib import Path

CLOSET_ROOT = str(Path(__file__).parent)
sys.path.insert(0, CLOSET_ROOT)

# Set PYTHONPATH so uvicorn's reloader subprocess inherits the path
existing = os.environ.get("PYTHONPATH", "")
if CLOSET_ROOT not in existing:
    os.environ["PYTHONPATH"] = f"{CLOSET_ROOT}:{existing}" if existing else CLOSET_ROOT

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from wardrobe.routes import router as wardrobe_router

app = FastAPI(
    title="Closet",
    description="AI-powered wardrobe manager and outfit recommender.",
    version="0.1.0",
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
