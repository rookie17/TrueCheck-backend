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
import re
from services.scrapers.blinkit import scrape_blinkit
from services.scrapers.bigbasket import get_product_by_name as bb_get_product_by_name
from services.barcode_resolver import resolve_product_name
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



def resolve_product(barcode: str) -> dict | None:
    # Step 1: OpenFoodFacts
    result = _resolve_openfoodfacts(barcode)
    if result and result.get("ingredients"):
        result["source"] = "openfoodfacts"
        return result

    # Step 2: Resolve name for scraper searches
    product_name = result.get("product_name") if result else None
    if not product_name or product_name == "Unknown":
        product_name = resolve_product_name(barcode)
    if not product_name:
        print(f"[Resolver] Could not resolve product name for {barcode}")
        return None

    # Clean name for search
    product_name = re.sub(r",?\s*\d+\.?\d*\s*(g|kg|ml|l|oz|lb)\b", "", product_name, flags=re.IGNORECASE).strip()

    # Step 3: BigBasket
    bb_data = bb_get_product_by_name(product_name)
    if bb_data and bb_data.get("ingredients_raw"):
        parts = [p.strip() for p in re.sub(r"\(\d+\.?\d*%\)", "", bb_data["ingredients_raw"]).split(",")]
        ingredients = [p for p in parts if len(p) > 1]
        if ingredients:
            print(f"[Resolver] Resolved {barcode} via bigbasket")
            return {
                "product_name":     bb_data.get("product_name", product_name),
                "ingredients":      ingredients,
                "nutrients_per_100g": bb_data.get("nutrition", {}),
                "_raw_off_product": None,
                "source":           "bigbasket",
            }

    # Step 4: Blinkit
    blinkit_data = scrape_blinkit(product_name)
    if blinkit_data and blinkit_data.get("ingredients"):
        print(f"[Resolver] Resolved {barcode} via blinkit")
        blinkit_data["source"] = "blinkit"
        blinkit_data.setdefault("_raw_off_product", None)
        return blinkit_data

    print(f"[Resolver] All sources exhausted for {barcode}")
    return None