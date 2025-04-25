import requests

def get_product_from_openfoodfacts(barcode):
    url = f"https://world.openfoodfacts.org/api/v2/product/{barcode}"
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        return data.get("product", {})
    return None
