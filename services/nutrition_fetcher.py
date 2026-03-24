import requests
from firestore import save_product_to_db

def fetch_nutrition_from_barcode(barcode):
    """
    Fetches nutritional content per 100g for a given barcode.
    Saves and returns only keys ending in '_100g'.
    """
    url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
    
    response = requests.get(url, timeout=10)
    data = response.json()
    if data.get("status") != 1:
        return None
    product = data.get("product", {})
    
    nutriments = product.get("nutriments", {})
    if not nutriments:
        return None

    # Filter only keys ending with '_100g'
    nutrition_100g = {
        k: v for k, v in nutriments.items() if k.endswith('_100g')
    }

    if not nutrition_100g:
        return None

    product_name = product.get("product_name", "Unknown")

    # Prepare full dict to save
    result = {
        "product_name": product_name,
        "barcode": barcode,
        "nutrients_per_100g": nutrition_100g
    }

    # Save to DB (can adjust if you save separately)# Save both product name and nutrition values
    save_product_to_db(barcode, product_name, [], nutrition_100g)


    return result
