"""Closet configuration — self-contained, no ai-twin dependency."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
WARDROBE_DIR = DATA_DIR / "wardrobe"
WARDROBE_INBOX = Path(os.environ.get(
    "WARDROBE_INBOX", os.path.expanduser("~/Downloads/wardrobe_inbox"),
))

for d in [DATA_DIR, WARDROBE_DIR, WARDROBE_DIR / "tops", WARDROBE_DIR / "bottoms",
          WARDROBE_DIR / "shoes", WARDROBE_DIR / "outfits"]:
    d.mkdir(parents=True, exist_ok=True)

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://sudhirabadugu@localhost:5433/ai_twin")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
