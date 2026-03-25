import requests

# OFf requires a descriptive User-Agent to avoid rate-limiting / blocks
_HEADERS = {
    "User-Agent": "TrueCheck/1.0 (health analyzer app; contact@truecheck.app)"
}


def get_product_from_openfoodfacts(barcode: str) -> dict | None:
    """
    Fetches raw product data from OpenFoodFacts by barcode.
    Returns the product dict, or None if not found or on error.
    """
    url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"

    try:
        response = requests.get(url, headers=_HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("status") != 1:
            return None

        product = data.get("product")
        # Guard against status=1 but empty/null product field (OFf edge case)
        if not product or not isinstance(product, dict):
            print(f"[OpenFoodFacts] status=1 but no product data for barcode {barcode}")
            return None

        return product

    except requests.exceptions.RequestException as e:
        print(f"[OpenFoodFacts] Request failed for barcode {barcode}: {e}")
        return None
    except Exception as e:
        print(f"[OpenFoodFacts] Unexpected error for barcode {barcode}: {e}")
        return None