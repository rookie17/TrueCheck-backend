import requests
from firestore import save_nutrition_to_db

def fetch_nutrition_from_barcode(barcode: str) -> dict | None:
    """
    Fetches nutritional content per 100g for a given barcode from OpenFoodFacts.
    Saves to DB and returns the result, or None if not found or on error.
    """
    url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"

    try:
        response = requests.get(url, timeout=10)
        data = response.json()
    except requests.exceptions.RequestException as e:
        print(f"[NutritionFetcher] Request failed for barcode {barcode}: {e}")
        return None
    except Exception as e:
        print(f"[NutritionFetcher] Unexpected error for barcode {barcode}: {e}")
        return None

    if data.get("status") != 1:
        return None

    product = data.get("product", {})
    nutriments = product.get("nutriments", {})
    if not nutriments:
        return None

    nutrition_100g = {k: v for k, v in nutriments.items() if k.endswith("_100g")}
    if not nutrition_100g:
        return None

    product_name = product.get("product_name", "Unknown")

    save_nutrition_to_db(barcode, nutrition_100g)
    
    return {
        "product_name": product_name,
        "barcode": barcode,
        "nutrients_per_100g": nutrition_100g
    }