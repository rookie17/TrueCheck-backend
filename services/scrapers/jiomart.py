"""
JioMart scraper — searches via their internal product search API.

Notes:
- JioMart's web app calls internal APIs at www.jiomart.com/api/.
  The search endpoint below is derived from network inspection.
- JioMart product pages embed product data in __NEXT_DATA__ and are
  relatively scraper-friendly compared to Blinkit/Zepto.
- Pincode is required for availability checks; 110001 (Delhi) is the default.
  Set JIOMART_PINCODE env var to override.
- Ingredient data quality on JioMart is inconsistent — some products have
  a dedicated `ingredients` field, others bury it in the description.
"""

import json
import os
import re
import requests
from bs4 import BeautifulSoup

_SEARCH_URL = "https://www.jiomart.com/api/getSearchData"
_PRODUCT_BASE = "https://www.jiomart.com"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.jiomart.com/",
}

_INGREDIENT_PATTERNS = [
    r"[Ii]ngredients?\s*[:\-]\s*(.+?)(?:\.|$|\n)",
    r"[Cc]ontains\s*[:\-]\s*(.+?)(?:\.|$|\n)",
    r"[Mm]ade\s+(?:with|from)\s*[:\-]?\s*(.+?)(?:\.|$|\n)",
]


def _extract_next_data(html: str) -> dict:
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', html, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


def _extract_ingredients_from_text(text: str) -> list[str]:
    if not text:
        return []
    for pattern in _INGREDIENT_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            raw = match.group(1).strip()
            return [i.strip() for i in re.split(r"[,;]", raw) if i.strip()]
    return []


def _parse_jiomart_product(product: dict) -> dict | None:
    name = (
        product.get("name")
        or product.get("productName")
        or product.get("title", "")
    ).strip()
    if not name:
        return None

    # Try structured ingredients field first
    ingredients = []
    raw_ing = product.get("ingredients") or product.get("ingredient_list", "")
    if isinstance(raw_ing, list):
        ingredients = [str(i).strip() for i in raw_ing if i]
    elif isinstance(raw_ing, str) and raw_ing.strip():
        ingredients = [i.strip() for i in re.split(r"[,;]", raw_ing) if i.strip()]

    if not ingredients:
        description = (
            product.get("description")
            or product.get("longDescription")
            or product.get("shortDescription", "")
        )
        ingredients = _extract_ingredients_from_text(description)

    # Nutrition
    nutrients = {}
    nutrition_info = product.get("nutritionInfo") or product.get("nutritionalInfo") or []
    if isinstance(nutrition_info, list):
        for entry in nutrition_info:
            if isinstance(entry, dict):
                key = entry.get("name", "").strip().lower().replace(" ", "_") + "_100g"
                val = entry.get("value") or entry.get("amount")
                if key and val is not None:
                    nutrients[key] = val

    return {
        "product_name": name,
        "ingredients": ingredients,
        "nutrients_per_100g": nutrients,
    }


def _search_jiomart(barcode: str) -> str | None:
    """Returns the first product page URL from JioMart search, or None."""
    pincode = os.getenv("JIOMART_PINCODE", "110001")
    try:
        resp = requests.get(
            _SEARCH_URL,
            headers=_HEADERS,
            params={"q": barcode, "pincode": pincode, "start": 0, "rows": 5},
            timeout=12,
        )
        if resp.status_code != 200:
            return None

        data = resp.json()
        products = (
            data.get("response", {}).get("docs", [])
            or data.get("products", [])
            or data.get("data", {}).get("products", [])
        )
        if not products:
            return None

        first = products[0]
        url = first.get("productUrl") or first.get("url") or first.get("pdpUrl", "")
        if not url:
            return None
        return url if url.startswith("http") else f"{_PRODUCT_BASE}{url}"

    except Exception as e:
        print(f"[JioMart] Search API error for barcode {barcode}: {e}")

    # Fallback: HTML search page
    try:
        resp = requests.get(
            f"{_PRODUCT_BASE}/search/{barcode}",
            headers=_HEADERS,
            timeout=12,
        )
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        link = soup.find("a", href=re.compile(r"/p/"))
        if link:
            href = link["href"]
            return href if href.startswith("http") else f"{_PRODUCT_BASE}{href}"
    except Exception as e:
        print(f"[JioMart] HTML search fallback failed for barcode {barcode}: {e}")

    return None


def scrape_jiomart(barcode: str) -> dict | None:
    product_url = _search_jiomart(barcode)
    if not product_url:
        print(f"[JioMart] No product URL found for barcode {barcode}")
        return None

    try:
        resp = requests.get(product_url, headers=_HEADERS, timeout=12)
        if resp.status_code != 200:
            print(f"[JioMart] Product page returned {resp.status_code}")
            return None

        next_data = _extract_next_data(resp.text)
        if next_data:
            page_props = next_data.get("props", {}).get("pageProps", {})
            product = (
                page_props.get("productDetails")
                or page_props.get("product")
                or page_props.get("pdpData", {}).get("product")
                or {}
            )
            if product:
                result = _parse_jiomart_product(product)
                if result:
                    return result

        # Fallback: try to parse structured JSON-LD from page
        soup = BeautifulSoup(resp.text, "html.parser")
        ld = soup.find("script", {"type": "application/ld+json"})
        if ld:
            try:
                ld_data = json.loads(ld.string or "")
                if isinstance(ld_data, dict):
                    result = _parse_jiomart_product(ld_data)
                    if result:
                        return result
            except json.JSONDecodeError:
                pass

        print(f"[JioMart] Could not extract product data from {product_url}")
        return None

    except requests.exceptions.Timeout:
        print(f"[JioMart] Timeout fetching {product_url}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[JioMart] Request error: {e}")
        return None
    except Exception as e:
        print(f"[JioMart] Unexpected error for barcode {barcode}: {e}")
        return None
