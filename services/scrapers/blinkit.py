"""
Blinkit scraper — searches by barcode via their internal v6 API.

Notes:
- Blinkit requires lat/lon headers to serve results (location-gated).
  Defaults to Delhi. Override via BLINKIT_LAT / BLINKIT_LON env vars.
- Their API returns product descriptions, not a dedicated ingredients field.
  Ingredients are parsed out of the description string.
- Bot detection is moderate. If this starts 403ing in prod, add a proxy
  or rotate User-Agent. Do NOT add Playwright here — keep scrapers lightweight.
- Endpoint verified as of mid-2024. If response shape changes, check
  `__NEXT_DATA__` on blinkit.com/search?q={barcode} as fallback.
"""

import os
import re
import requests

_SEARCH_URL = "https://blinkit.com/v6/search/products"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://blinkit.com/",
    "Origin": "https://blinkit.com",
    "app_version": "1000000",
    "web": "1",
    "lat": os.getenv("BLINKIT_LAT", "28.6139"),
    "lon": os.getenv("BLINKIT_LON", "77.2090"),
}

_INGREDIENT_PATTERNS = [
    r"[Ii]ngredients?\s*[:\-]\s*(.+?)(?:\.|$|\n)",
    r"[Cc]ontains\s*[:\-]\s*(.+?)(?:\.|$|\n)",
    r"[Mm]ade\s+(?:with|from)\s*[:\-]?\s*(.+?)(?:\.|$|\n)",
]


def _extract_ingredients_from_text(text: str) -> list[str]:
    if not text:
        return []
    for pattern in _INGREDIENT_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            raw = match.group(1).strip()
            return [i.strip() for i in re.split(r"[,;]", raw) if i.strip()]
    return []


def _parse_product(obj: dict) -> dict | None:
    """Extracts normalized fields from a Blinkit product object."""
    name = obj.get("name", "").strip()
    if not name:
        return None

    description = obj.get("description", "") or ""
    ingredients = _extract_ingredients_from_text(description)

    # Blinkit doesn't expose structured nutrition — leave empty
    return {
        "product_name": name,
        "ingredients": ingredients,
        "nutrients_per_100g": {},
    }


def scrape_blinkit(barcode: str) -> dict | None:
    try:
        response = requests.get(
            _SEARCH_URL,
            headers=_HEADERS,
            params={"q": barcode, "start": 0, "size": 10},
            timeout=12,
        )

        if response.status_code == 403:
            print(f"[Blinkit] 403 — likely bot-blocked for barcode {barcode}")
            return None
        if response.status_code != 200:
            print(f"[Blinkit] Unexpected status {response.status_code} for barcode {barcode}")
            return None

        data = response.json()

        # Response shape: data -> objects -> list of {type, data: {...}}
        objects = (
            data.get("data", {}).get("objects", [])
            or data.get("objects", [])  # handle shape drift
        )

        for obj in objects:
            inner = obj.get("data", obj)  # some versions nest, some don't
            if not isinstance(inner, dict):
                continue
            result = _parse_product(inner)
            if result and result["ingredients"]:
                return result

        print(f"[Blinkit] No usable product found for barcode {barcode}")
        return None

    except requests.exceptions.Timeout:
        print(f"[Blinkit] Timeout for barcode {barcode}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[Blinkit] Request error for barcode {barcode}: {e}")
        return None
    except Exception as e:
        print(f"[Blinkit] Unexpected error for barcode {barcode}: {e}")
        return None
