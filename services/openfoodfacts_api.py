import requests

def get_product_from_openfoodfacts(barcode):
    url = f"https://world.openfoodfacts.org/api/v2/product/{barcode}"
    response = requests.get(url, timeout=10)
    data = response.json()
    if data.get("status") != 1:
        return None
    return data.get("product", {})