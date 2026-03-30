from firestore import db, save_percent_estimate_to_db
from services.openfoodfacts_api import get_product_from_openfoodfacts
from utils.ingredient_utils import extract_ingredient_text


def get_percent_estimates(barcode, ingredient_names, product_data=None):
    product_doc = db.collection("products").document(barcode).get()
    if product_doc.exists:
        existing_data = product_doc.to_dict()
        if "percent_estimate" in existing_data:
            return existing_data["percent_estimate"]

    if product_data is None:
        product_data = get_product_from_openfoodfacts(barcode)
    if not product_data:
        return ["Not Available"] * len(ingredient_names)

    percent_list = []
    for ing in ingredient_names:
        ing_str = ing if isinstance(ing, str) else ing.get("name", "")
        match = next(
            (item.get("percent_estimate") for item in product_data.get("ingredients", [])
             if isinstance(item, dict) and  extract_ingredient_text(item).lower() == ing_str.lower()),
            "Not Available"
        )
        percent_list.append(match if match is not None else "Not Available")

    save_percent_estimate_to_db(barcode, percent_list)
    return percent_list