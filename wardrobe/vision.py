"""
Wardrobe Vision — photo analysis and garment image extraction.

Uses Gemini Vision for clothing detection and Gemini image generation
for clean catalog-style garment images.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import base64
import json
from io import BytesIO

from PIL import Image

from config import GOOGLE_API_KEY

MAX_IMAGE_SIZE = (1024, 1024)  # resize before sending to Vision API
THUMB_SIZE = (400, 400)        # stored thumbnails


def image_to_base64(path: Path, max_size: tuple = MAX_IMAGE_SIZE) -> tuple[str, str]:
    """Load an image, resize, and return (base64_data, media_type)."""
    img = Image.open(path)
    img = img.convert("RGB")
    img.thumbnail(max_size, Image.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return b64, "image/jpeg"


def analyze_photo(image_b64: str, media_type: str) -> dict | None:
    """Use Gemini Vision to extract clothing items with rich metadata + scene context.

    Extracts per item: category, fabric/texture, weather suitability (natural language),
    style vibe, occasion, and full description. Scene context is linked to each item.

    Returns dict with: photo_type, is_clothing, items[], scene{}
    """
    from google import genai
    from google.genai import types

    if not GOOGLE_API_KEY:
        print("  GOOGLE_API_KEY not set")
        return None

    prompt = """Analyze this photo. Return JSON only, no markdown.

RULES — identify ALL clothing items the person is wearing:
- "dress" = one-piece garment covering torso to at least mid-thigh (maxi, midi, mini, gown, sundress, jumpsuit, romper)
- "top" = upper body only (shirt, blouse, sweater, jacket, t-shirt, tank top, hoodie, cardigan, coat)
- "bottom" = lower body only (pants, trousers, jeans, leggings, skirt, shorts, joggers)
- "shoes" = footwear (sneakers, heels, boots, sandals, flats, loafers)

For EACH item extract:
1. FABRIC — look at the surface texture: knit/ribbed, smooth cotton, silk/satin, denim, linen, leather, suede, fleece, chiffon, jersey, wool, polyester. Be specific.
2. WEATHER SUITABILITY — describe what weather this works for in natural language. Consider fabric weight, coverage, breathability. Use Celsius. Example: "lightweight breathable cotton, ideal for warm sunny days 25-35C" or "thick knit wool, warm insulating layer for cold weather 0-10C"
3. STYLE VIBE — what aesthetic: bohemian, minimalist, professional, athleisure, romantic, streetwear, classic, preppy, edgy, cozy-casual
4. OCCASION — what is this suited for, considering both the garment AND the scene: office, brunch, hiking, date night, beach day, everyday errands, gym, travel, party, formal event

SCENE — analyze the background/setting of the photo.

If no person wearing clothes is visible, set is_clothing to false.

{
  "is_clothing": true,
  "photo_type": "solo|group|closeup|other",
  "scene": {
    "location_type": "beach|restaurant|trail|park|mall|city_street|countryside|garden|home|office|event_venue|other",
    "landmark_or_name": "",
    "activity": "",
    "scene_description": "brief scene description",
    "vibe": "casual_outing|adventure|date_night|travel|work|fitness|celebration|everyday"
  },
  "items": [
    {
      "category": "top|bottom|dress|shoes",
      "subcategory": "e.g. ribbed crew-neck sweater, straight-leg jeans, maxi sundress, ankle boots",
      "color": "descriptive color(s)",
      "pattern": "solid|striped|plaid|graphic|floral|abstract|geometric|other",
      "fabric": "e.g. chunky knit wool, smooth cotton, raw denim, soft jersey, silk chiffon",
      "description": "10-15 word description including fabric feel and silhouette",
      "weather_suitability": "natural language: what temperature range (Celsius) and conditions this works for and why",
      "season": "summer|winter|spring_fall|all_season",
      "comfort": "casual|smart_casual|formal|athletic|loungewear",
      "style_vibe": "e.g. bohemian, minimalist, professional, athleisure, cozy-casual",
      "style_tags": ["e.g. minimalist", "layering piece", "statement"],
      "suited_for": "e.g. beach day, office meeting, hiking, brunch, date night"
    }
  ]
}"""

    image_bytes = base64.b64decode(image_b64)

    try:
        client = genai.Client(api_key=GOOGLE_API_KEY)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=media_type),
                prompt,
            ],
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw[:-3].strip()
        return json.loads(raw)
    except Exception as e:
        print(f"  Gemini analysis error: {e}")
        return None


def gemini_extract_garment(image_b64: str, media_type: str, category: str,
                           item_description: str = "") -> bytes | None:
    """Use Gemini to generate a clean catalog-style garment image.

    Sends the photo to Gemini and asks it to extract the specified garment
    as a clean product image (Zara-style) with white background, no face.

    Args:
        item_description: Specific description from Vision API (e.g. "brown zip-up
            athletic jacket with a high collar"). When provided, Gemini targets
            this exact garment instead of picking any item in the category.

    Returns PNG image bytes or None on failure.
    """
    from google import genai
    from google.genai import types

    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY not set — required for Gemini garment extraction")

    client = genai.Client(api_key=GOOGLE_API_KEY)

    if item_description:
        # Specific prompt: Vision already identified the exact garment
        cat_label = {"tops": "top", "bottoms": "bottom", "dresses": "dress", "shoes": "shoes"}.get(category, category)
        prompt = (
            f"Extract ONLY this specific {cat_label} from the photo: {item_description}. "
            f"Generate a clean product image showing just this garment, "
            f"laid flat or on an invisible mannequin, on a pure white background. "
            f"NO face, NO person, NO other clothing — just this one item, like a Zara product page."
        )
    else:
        # Fallback: generic category prompt
        category_prompts = {
            "tops": "Extract ONLY the top (shirt/blouse/sweater) from this photo. "
                    "Generate a clean product image showing just the top garment, "
                    "laid flat or on an invisible mannequin, on a pure white background. "
                    "NO face, NO person, NO other clothing — just the top, like a Zara product page.",
            "bottoms": "Extract ONLY the bottom (pants/trousers/skirt/leggings) from this photo. "
                       "Generate a clean product image showing just the bottom garment, "
                       "laid flat or on an invisible mannequin, on a pure white background. "
                       "NO face, NO person, NO other clothing — just the bottom, like a Zara product page.",
            "dresses": "Extract ONLY the dress from this photo. "
                       "Generate a clean product image showing just the dress, "
                       "laid flat or on an invisible mannequin, on a pure white background. "
                       "NO face, NO person — just the dress, like a Zara product page.",
            "shoes": "Extract ONLY the shoes from this photo. "
                     "Generate a clean product image showing just the pair of shoes, "
                     "on a pure white background, like a Zara product page.",
        }
        prompt = category_prompts.get(category, category_prompts["tops"])
    image_bytes = base64.b64decode(image_b64)

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=media_type),
                prompt,
            ],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        )

        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                return part.inline_data.data

        return None
    except Exception as e:
        print(f"  Gemini garment extraction failed: {e}")
        return None


def extract_garment_image(image_path: Path, output_path: Path,
                          category: str = "", image_b64: str = "",
                          media_type: str = "image/jpeg",
                          item_description: str = "") -> bool:
    """Generate a clean Zara-style catalog image of a specific garment using Gemini.

    When item_description is provided (from Vision API), Gemini targets that
    exact garment instead of picking any item in the category.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not image_b64 or not category:
        return False

    try:
        img_bytes = gemini_extract_garment(image_b64, media_type, category,
                                           item_description=item_description)
        if img_bytes:
            from io import BytesIO
            img = Image.open(BytesIO(img_bytes))
            img.thumbnail(THUMB_SIZE, Image.LANCZOS)
            img.convert("RGB").save(output_path, format="PNG", quality=95)
            print(f"    Gemini: clean {category} image generated")
            return True
        print(f"    Gemini: no image returned for {category}")
        return False
    except Exception as e:
        print(f"    Gemini extraction failed: {e}")
        return False


def get_weather(lat: float = 37.7749, lon: float = -122.4194) -> dict:
    """Fetch current weather from Open-Meteo API (free, no key needed).

    Defaults to San Francisco. Override with user's location.
    """
    import httpx

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
        f"&temperature_unit=celsius"
    )

    try:
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        current = data.get("current", {})

        temp_c = current.get("temperature_2m", 20)
        humidity = current.get("relative_humidity_2m", 50)
        weather_code = current.get("weather_code", 0)

        wmo_map = {
            0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
            45: "fog", 48: "freezing fog",
            51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
            61: "slight rain", 63: "moderate rain", 65: "heavy rain",
            71: "slight snow", 73: "moderate snow", 75: "heavy snow",
            80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers",
            95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
        }
        condition = wmo_map.get(weather_code, "unknown")

        return {
            "temp_c": temp_c,
            "temp_f": round(temp_c * 9 / 5 + 32, 1),
            "humidity": humidity,
            "condition": condition,
            "wind_speed_kmh": current.get("wind_speed_10m", 0),
        }
    except Exception as e:
        return {"temp_c": 20, "temp_f": 68, "humidity": 50, "condition": "unknown", "error": str(e)}
