"""
Product resolver — single entry point for all data sources.
Tries each source in priority order, returns first successful normalized result.

Normalized return shape:
{
    "product_name": str,
    "ingredients": [str],          # plain strings, already extracted
    "nutrients_per_100g": dict,    # may be empty {}
    "source": str,                 # which service resolved it
    "_raw_off_product": dict|None  # only set when source=openfoodfacts, for percent_estimate
}
"""

from services.openfoodfacts_api import get_product_from_openfoodfacts
from services.scrapers.blinkit import scrape_blinkit
from services.scrapers.bigbasket import scrape_bigbasket
from services.scrapers.zepto import scrape_zepto
from services.scrapers.jiomart import scrape_jiomart
from utils.ingredient_utils import extract_ingredient_text


def _resolve_openfoodfacts(barcode: str) -> dict | None:
    product = get_product_from_openfoodfacts(barcode)
    if not product:
        return None

    ingredients = [
        extract_ingredient_text(i)
        for i in product.get("ingredients", [])
        if extract_ingredient_text(i)
    ]
    nutriments = product.get("nutriments", {})
    nutrition = {k: v for k, v in nutriments.items() if k.endswith("_100g")}

    if not ingredients and not nutrition:
        return None

    return {
        "product_name": product.get("product_name", "Unknown"),
        "ingredients": ingredients,
        "nutrients_per_100g": nutrition,
        "_raw_off_product": product,  # preserved for percent_estimate extraction
    }


# Priority order — edit here to reorder or disable sources
_RESOLVERS = [
    ("openfoodfacts", _resolve_openfoodfacts),
    ("blinkit",       scrape_blinkit),
    ("bigbasket",     scrape_bigbasket),
    ("zepto",         scrape_zepto),
    ("jiomart",       scrape_jiomart),
]


def resolve_product(barcode: str) -> dict | None:
    """
    Tries each resolver in order. Returns the first non-None result
    with a 'source' key injected, or None if all sources fail.
    """
    for source_name, resolver in _RESOLVERS:
        try:
            result = resolver(barcode)
            if result and result.get("ingredients"):
                result.setdefault("_raw_off_product", None)
                result["source"] = source_name
                print(f"[Resolver] Resolved barcode {barcode} via {source_name}")
                return result
        except Exception as e:
            print(f"[Resolver] {source_name} raised an exception for {barcode}: {e}")
            continue

    print(f"[Resolver] All sources exhausted for barcode {barcode}")
    return None
