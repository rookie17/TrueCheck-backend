import requests

def get_product_from_openfoodfacts(barcode):
    url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
    headers = {"User-Agent": "TrueCheck-App/1.0 (student project)"}
    response = requests.get(url, headers=headers, timeout=10)

    if response.status_code == 200:
        data = response.json()
        if data.get("status") == 0:   # product not found
            return None
        return data.get("product", {})
    return None
