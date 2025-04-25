from firestore import db, save_percent_estimate_to_db
from services.openfoodfacts_api import get_product_from_openfoodfacts

def get_percent_estimates(barcode, ingredients):
    # Step 1: Try to fetch from DB
    estimate_ref = db.collection("products").document(barcode).collection("extra").document("percent_estimate")
    doc = estimate_ref.get()
    
    if doc.exists:
        return doc.to_dict().get("values", [])

    # Step 2: Fallback to OpenFoodFacts
    product_data = get_product_from_openfoodfacts(barcode)
    if not product_data:
        return ["Not Avail"] * len(ingredients)

    percent_list = []
    for ing in ingredients:
        match = next(
            (item.get("percent_estimate") for item in product_data.get("ingredients", []) 
             if item.get("text", "").lower() == ing.lower()), 
            "Not Available"
        )
        percent_list.append(match if match is not None else "Not Available")

    # Step 3: Save to Firestore
    estimate_ref.set({"values": percent_list})
    # At the end of get_percent_estimate()
    save_percent_estimate_to_db(barcode, percent_list)

    return percent_list
