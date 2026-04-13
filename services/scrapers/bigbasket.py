import json
import re
import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://www.bigbasket.com"
SEARCH_URL = f"{BASE_URL}/listing-svc/v2/products"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json,*/*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.bigbasket.com/",
}

# Map BB nutrition label prefixes to OFf-style _100g keys
_NUTRITION_KEY_MAP = {
    "energy": "energy_100g",
    "protein": "proteins_100g",
    "carbohydrate": "carbohydrates_100g",
    "total sugars": "sugars_100g",
    "added sugars": "added-sugars_100g",
    "total fat": "fat_100g",
    "saturated fat": "saturated-fat_100g",
    "trans fat": "trans-fat_100g",
    "fiber": "fiber_100g",
    "sodium": "sodium_100g",
    "iron": "iron_100g",
    "calcium": "calcium_100g",
    "vitamin b9": "vitamin-b9_100g",
}


def _normalize_nutrition_key(raw_key: str) -> str:
    """Map BB nutrition label to OFf-style _100g key where possible."""
    lower = raw_key.lower().strip()
    for bb_key, off_key in _NUTRITION_KEY_MAP.items():
        if lower.startswith(bb_key):
            return off_key
    # fallback: sanitize and append _100g
    sanitized = re.sub(r"[^a-z0-9]+", "-", lower).strip("-")
    return f"{sanitized}_100g"


def _normalize_nutrition_value(raw_val: str) -> float | str:
    """Strip units and convert to float where possible."""
    # e.g. "166 kcal", "4.2 g", "10,916 mg"
    match = re.search(r"[\d,]+\.?\d*", raw_val)
    if match:
        try:
            return float(match.group(0).replace(",", ""))
        except ValueError:
            pass
    return raw_val


def _extract_next_data(html: str) -> dict:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.DOTALL
    )
    if not match:
        raise ValueError("__NEXT_DATA__ not found in page")
    return json.loads(match.group(1))


def _parse_tab_text(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def _extract_ingredients(tabs: list[dict]) -> str:
    for tab in tabs:
        if tab.get("title") == "Ingredients":
            soup = BeautifulSoup(tab["content"], "html.parser")
            first_p = soup.find("p")
            if first_p:
                return first_p.get_text(separator=" ", strip=True)
            return soup.get_text(separator=" ", strip=True)
    return ""


def _extract_nutrition(tabs: list[dict]) -> dict:
    """
    Try 'Nutritional Facts' tab first (structured plain text).
    Fall back to parsing the <ul> inside 'Ingredients' tab.
    Returns dict with OFf-style _100g keys.
    """
    nutrition = {}

    for tab in tabs:
        if tab.get("title") == "Nutritional Facts":
            text = _parse_tab_text(tab["content"])
            for line in text.splitlines():
                line = line.strip()
                if ":" in line:
                    raw_key, _, raw_val = line.partition(":")
                    key = _normalize_nutrition_key(raw_key)
                    nutrition[key] = _normalize_nutrition_value(raw_val.strip())
            if nutrition:
                return nutrition

    for tab in tabs:
        if tab.get("title") == "Ingredients":
            soup = BeautifulSoup(tab["content"], "html.parser")
            ul = soup.find("ul")
            if ul:
                for li in ul.find_all("li"):
                    text = li.get_text(strip=True)
                    if ":" in text:
                        raw_key, _, raw_val = text.partition(":")
                        key = _normalize_nutrition_key(raw_key)
                        nutrition[key] = _normalize_nutrition_value(raw_val.strip())
            return nutrition

    return nutrition

def search_by_name(product_name: str, bucket_id: int = 76) -> list[dict]:
    """Hit BB listing API, return raw product list."""
    session = requests.Session()
    session.headers.update(_HEADERS)

    try:
        # Seed session cookies by hitting the homepage first
        session.get(BASE_URL, timeout=10)
    except Exception as e:
        logger.warning(f"BB: failed to seed session cookies: {e}")

    try:
        resp = session.get(
            SEARCH_URL,
            params={"type": "ps", "slug": product_name, "page": 1, "bucket_id": bucket_id},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        tabs = data.get("tabs", [])
        if not tabs:
            return []
        return tabs[0].get("product_info", {}).get("products", [])
    except Exception as e:
        logger.error(f"BB search failed for '{product_name}': {e}")
        return []

def get_product_details(absolute_url: str) -> dict | None:
    """
    Fetch BB product detail page, extract ingredients + nutrition
    from __NEXT_DATA__ JSON embedded in the SSR HTML.
    No JS rendering required.
    """
    url = f"{BASE_URL}{absolute_url}" if absolute_url.startswith("/") else absolute_url
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15, allow_redirects=True)
        resp.raise_for_status()
        next_data = _extract_next_data(resp.text)
    except Exception as e:
        logger.error(f"BB product page fetch failed {url}: {e}")
        return None

    try:
        product = next_data["props"]["pageProps"]["productDetails"]
        sku = product["children"][0] if product.get("children") else product
        tabs = sku.get("tabs", [])

        ingredients_raw = _extract_ingredients(tabs)
        nutrition = _extract_nutrition(tabs)

        food_type_info = sku.get("additional_attr", {}).get("info", [])
        food_type = next(
            (i.get("sub_type") for i in food_type_info if i.get("type") == "food_type"),
            None,
        )

        return {
            "product_name": sku.get("desc", ""),
            "brand": sku.get("brand", {}).get("name", ""),
            "ingredients_raw": ingredients_raw,
            "nutrition": nutrition,
            "food_type": food_type,
            "bb_url": url,
            "source": "bigbasket",
        }
    except (KeyError, IndexError) as e:
        logger.error(f"BB __NEXT_DATA__ parse failed for {url}: {e}")
        return None


def get_product_by_name(product_name: str, bucket_id: int = 76) -> dict | None:
    """
    Search BB by name → take first result → fetch detail page.
    Returns structured dict or None.
    """
    products = search_by_name(product_name, bucket_id)
    if not products:
        logger.warning(f"BB: no search results for '{product_name}'")
        return None

    absolute_url = products[0].get("absolute_url")
    if not absolute_url:
        logger.warning(f"BB: no absolute_url in first result for '{product_name}'")
        return None

    logger.info(f"BB: fetching {absolute_url}")
    return get_product_details(absolute_url)