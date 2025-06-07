from firestore import db, save_percent_estimate_to_db
from services.openfoodfacts_api import get_product_from_openfoodfacts

def get_percent_estimates(barcode, ingredient_names):
    # Step 1: Try to fetch from main product document
    product_doc = db.collection("products").document(barcode).get()
    if product_doc.exists:
        existing_data = product_doc.to_dict()
        if "percent_estimate" in existing_data:
            return existing_data["percent_estimate"]

    # Step 2: Fallback to OpenFoodFacts
    product_data = get_product_from_openfoodfacts(barcode)
    if not product_data:
        return ["Not Available"] * len(ingredient_names)

    percent_list = []
    for ing in ingredient_names:
        match = next(
            (item.get("percent_estimate") for item in product_data.get("ingredients", [])
             if item.get("text", "").lower() == ing.lower()),
            "Not Available"
        )
        percent_list.append(match if match is not None else "Not Available")

    # Step 3: Save to Firestore main product doc
    save_percent_estimate_to_db(barcode, percent_list)

    return percent_list
