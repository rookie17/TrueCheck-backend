"""
Zepto scraper — searches via their internal search API.

Notes:
- Zepto is app-first. Their web frontend is a Next.js SPA that calls
  internal APIs at api.zeptonow.com. The endpoints below work as of mid-2024
  but are undocumented and can change without notice.
- Store ID is required. "1" is a safe default (Mumbai central store).
  Override via ZEPTO_STORE_ID env var if you get empty results.
- If the API starts failing, the fallback is __NEXT_DATA__ extraction
  from zeptonow.com/search?query={barcode}, but Zepto's web is heavily
  JS-rendered and may not contain full product data in SSR output.
- Ingredients are embedded in product description — same regex extraction
  as other scrapers.
"""

import os
import re
import requests

_SEARCH_URL = "https://api.zeptonow.com/api/v3/search"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://www.zeptonow.com",
    "Referer": "https://www.zeptonow.com/",
    "app_version": "1",
    "tenant": "zepto",
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


def _parse_zepto_product(product: dict) -> dict | None:
    name = (product.get("name") or product.get("product_name", "")).strip()
    if not name:
        return None

    description = (
        product.get("description")
        or product.get("long_description")
        or product.get("mrp_details", {}).get("description", "")
        or ""
    )
    ingredients = _extract_ingredients_from_text(description)

    return {
        "product_name": name,
        "ingredients": ingredients,
        "nutrients_per_100g": {},  # Zepto doesn't expose structured nutrition
    }


def scrape_zepto(barcode: str) -> dict | None:
    store_id = os.getenv("ZEPTO_STORE_ID", "1")

    try:
        response = requests.get(
            _SEARCH_URL,
            headers=_HEADERS,
            params={
                "query": barcode,
                "page_number": 0,
                "page_size": 10,
                "store_id": store_id,
            },
            timeout=12,
        )

        if response.status_code == 403:
            print(f"[Zepto] 403 — likely bot-blocked for barcode {barcode}")
            return None
        if response.status_code != 200:
            print(f"[Zepto] Unexpected status {response.status_code} for barcode {barcode}")
            return None

        data = response.json()

        # Response path varies: data -> sections -> items | products
        sections = data.get("data", {}).get("sections", []) or []
        for section in sections:
            items = section.get("items") or section.get("products") or []
            for item in items:
                product = item.get("product") or item.get("data") or item
                if not isinstance(product, dict):
                    continue
                result = _parse_zepto_product(product)
                if result and result["ingredients"]:
                    return result

        # Flat product list fallback
        products = data.get("data", {}).get("products", []) or data.get("products", [])
        for product in products:
            result = _parse_zepto_product(product)
            if result and result["ingredients"]:
                return result

        print(f"[Zepto] No usable product found for barcode {barcode}")
        return None

    except requests.exceptions.Timeout:
        print(f"[Zepto] Timeout for barcode {barcode}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[Zepto] Request error for barcode {barcode}: {e}")
        return None
    except Exception as e:
        print(f"[Zepto] Unexpected error for barcode {barcode}: {e}")
        return None
