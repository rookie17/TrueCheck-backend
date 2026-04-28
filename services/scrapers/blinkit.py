"""
services/scrapers/blinkit.py
=============================
Blinkit scraper — rebuilt from real DevTools network inspection.

Flow:
  1. Search API  → GET /v1/layout/search?q={name} → extract product_id from snippets
  2. Detail API  → GET /v1/layout/product/{product_id} → extract ingredients + nutrition

Response structure is UI-driven JSON (not clean fields).
Ingredients and nutrition are found by scanning for objects where
title.text matches the section name, then reading subtitle.text.

Auth note:
  The live session uses auth_key, device_id, session_uuid headers.
  These are session-specific and will expire. We attempt without them first.
  If Blinkit starts returning 401/403, set BLINKIT_AUTH_KEY, BLINKIT_DEVICE_ID,
  BLINKIT_SESSION_UUID in .env — but be aware these will need manual rotation.
"""

import os
import re
import requests

_BASE_URL = "https://blinkit.com"
_SEARCH_URL = f"{_BASE_URL}/v1/layout/search"
_DETAIL_URL = f"{_BASE_URL}/v1/layout/product"

# Nutrition label → OFf-style _100g key mapping
_NUTRITION_KEY_MAP = {
    "energy":          "energy_100g",
    "protein":         "proteins_100g",
    "carbohydrate":    "carbohydrates_100g",
    "total sugar":     "sugars_100g",
    "added sugar":     "added-sugars_100g",
    "total fat":       "fat_100g",
    "saturated fat":   "saturated-fat_100g",
    "trans fat":       "trans-fat_100g",
    "dietary fiber":   "fiber_100g",
    "sodium":          "sodium_100g",
    "calcium":         "calcium_100g",
    "iron":            "iron_100g",
}


def _build_headers() -> dict:
    headers = {
        "User-Agent":        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept":            "application/json, text/plain, */*",
        "Accept-Language":   "en-IN,en;q=0.9",
        "Referer":           "https://blinkit.com/",
        "Origin":            "https://blinkit.com",
        # Required by Blinkit — verified from DevTools
        "lat":               os.getenv("BLINKIT_LAT", "28.544147"),
        "lon":               os.getenv("BLINKIT_LON", "77.115980"),
        "app_client":        "consumer_web",
        "app_version":       "1010101010",
        "web_app_version":   "1008010016",
        "rn_bundle_version": "1009003012",
    }

    # Session-specific — optional, will expire, set in .env if needed
    auth_key     = os.getenv("BLINKIT_AUTH_KEY")
    device_id    = os.getenv("BLINKIT_DEVICE_ID")
    session_uuid = os.getenv("BLINKIT_SESSION_UUID")

    if auth_key:
        headers["auth_key"] = auth_key
    if device_id:
        headers["device_id"] = device_id
    if session_uuid:
        headers["session_uuid"] = session_uuid

    return headers


# ─── Response traversal ───────────────────────────────────────────────────────

def _find_section_text(data, section_title: str) -> str | None:
    """
    Recursively walk the UI-driven JSON to find an object where
    title.text == section_title, and return its subtitle.text.
    """
    if isinstance(data, dict):
        title = data.get("title", {})
        if isinstance(title, dict) and title.get("text") == section_title:
            subtitle = data.get("subtitle", {})
            if isinstance(subtitle, dict):
                return subtitle.get("text", "").strip() or None

        for value in data.values():
            result = _find_section_text(value, section_title)
            if result:
                return result

    elif isinstance(data, list):
        for item in data:
            result = _find_section_text(item, section_title)
            if result:
                return result

    return None


def _find_product_id_in_snippets(data) -> str | None:
    """
    Recursively search snippets structure for a product_id string.
    Blinkit wraps products inside snippets[i].data.
    """
    if isinstance(data, dict):
        pid = data.get("product_id")
        if pid:
            return str(pid)
        for value in data.values():
            result = _find_product_id_in_snippets(value)
            if result:
                return result

    elif isinstance(data, list):
        for item in data:
            result = _find_product_id_in_snippets(item)
            if result:
                return result

    return None


# ─── Ingredient parsing ───────────────────────────────────────────────────────

def _split_ingredients(raw: str) -> list[str]:
    """
    Parse a raw ingredients string into a clean list.
    Handles nested parens (e.g. "Salt, Sugar (Cane (Raw))") by splitting
    only on top-level commas.
    """
    ingredients = []
    depth = 0
    current = []

    for char in raw:
        if char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            part = "".join(current).strip()
            if part and len(part) > 1:
                ingredients.append(part)
            current = []
        else:
            current.append(char)

    last = "".join(current).strip()
    if last and len(last) > 1:
        ingredients.append(last)

    return ingredients


def _parse_ingredients(raw: str) -> list[str]:
    """
    Blinkit ingredient strings often have section header prefixes like
    'NOODLES: Refined wheat flour..., TASTEMAKER: Salt, ...'
    Strip those headers and flatten into one list.
    """
    if not raw:
        return []

    # Remove percentage annotations like (10%), (3.5%)
    cleaned = re.sub(r"\(\d+\.?\d*\s*%\)", "", raw)

    # Split on ALL-CAPS section headers (e.g. "NOODLES:", "TASTEMAKER:")
    sections = re.split(r"\b[A-Z][A-Z\s]{2,}:\s*", cleaned)

    ingredients = []
    for section in sections:
        ingredients.extend(_split_ingredients(section))

    # Final clean: strip stray punctuation, filter empties and pure numbers
    return [
        re.sub(r"^[\s\-\.]+|[\s\-\.]+$", "", i)
        for i in ingredients
        if i and not i.replace(".", "").replace(",", "").isdigit()
    ]


# ─── Nutrition parsing ────────────────────────────────────────────────────────

def _parse_nutrition(raw: str) -> dict:
    """
    Parse Blinkit's flat nutrition text into OFf-style _100g dict.

    Input example:
      "Protein Per 100 g (g) 7.2 g ... Energy per 100g (Kcal) 369 Kcal"

    Strategy: scan for known nutrient names, grab the first numeric value
    that follows each match.
    """
    if not raw:
        return {}

    nutrition = {}
    lower = raw.lower()

    for label, off_key in _NUTRITION_KEY_MAP.items():
        idx = lower.find(label)
        if idx == -1:
            continue
        after = raw[idx + len(label):]
        match = re.search(r"[\d,]+\.?\d*", after)
        if match:
            try:
                nutrition[off_key] = float(match.group(0).replace(",", ""))
            except ValueError:
                pass

    return nutrition


# ─── API calls ────────────────────────────────────────────────────────────────

def _search(product_name: str) -> str | None:
    """Search Blinkit by name, return first product_id or None."""
    try:
        resp = requests.get(
            _SEARCH_URL,
            headers=_build_headers(),
            params={
                "q":           product_name,
                "offset":      0,
                "limit":       10,
                "search_type": "type_to_search",
            },
            timeout=12,
        )

        if resp.status_code == 401:
            print("[Blinkit] 401 — auth headers may be required. Set BLINKIT_AUTH_KEY in .env")
            return None
        if resp.status_code == 403:
            print("[Blinkit] 403 — bot-blocked")
            return None
        if resp.status_code != 200:
            print(f"[Blinkit] Search returned {resp.status_code} for '{product_name}'")
            return None

        data = resp.json()
        product_id = _find_product_id_in_snippets(data)

        if not product_id:
            print(f"[Blinkit] No product_id in search response for '{product_name}'")
            return None

        return product_id

    except requests.exceptions.Timeout:
        print(f"[Blinkit] Search timeout for '{product_name}'")
        return None
    except Exception as e:
        print(f"[Blinkit] Search error for '{product_name}': {e}")
        return None


def _fetch_product_detail(product_id: str) -> dict | None:
    """Fetch full product detail page JSON by product_id."""
    try:
        resp = requests.get(
            f"{_DETAIL_URL}/{product_id}",
            headers=_build_headers(),
            timeout=12,
        )

        if resp.status_code != 200:
            print(f"[Blinkit] Detail API returned {resp.status_code} for product {product_id}")
            return None

        return resp.json()

    except requests.exceptions.Timeout:
        print(f"[Blinkit] Detail timeout for product {product_id}")
        return None
    except Exception as e:
        print(f"[Blinkit] Detail error for product {product_id}: {e}")
        return None


# ─── Public interface ─────────────────────────────────────────────────────────

def scrape_blinkit(product_name: str) -> dict | None:
    """
    Search Blinkit by product name → fetch detail → return normalized dict.

    Returns:
        {
            "product_name": str,
            "ingredients": [str],
            "nutrients_per_100g": dict,
            "source": "blinkit"
        }
        or None if lookup fails at any step.
    """
    product_id = _search(product_name)
    if not product_id:
        return None

    print(f"[Blinkit] Found product_id={product_id} for '{product_name}'")

    detail = _fetch_product_detail(product_id)
    if not detail:
        return None

    ingredients_raw = _find_section_text(detail, "Ingredients")
    nutrition_raw   = _find_section_text(detail, "Nutrition Information")

    ingredients = _parse_ingredients(ingredients_raw or "")
    nutrition   = _parse_nutrition(nutrition_raw or "")

    # Dig product name out of detail response (more accurate than search input)
    product_name_resolved = _find_section_text(detail, "Product Name") or product_name

    if not ingredients:
        print(f"[Blinkit] No ingredients found for product_id={product_id}")
        return None

    return {
        "product_name":       product_name_resolved,
        "ingredients":        ingredients,
        "nutrients_per_100g": nutrition,
        "source":             "blinkit",
    }