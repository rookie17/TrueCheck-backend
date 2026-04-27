from firestore import db, save_percent_estimate_to_db
from services.openfoodfacts_api import get_product_from_openfoodfacts


def _get_ingredient_text(item):
    text = item.get("text", "")
    if isinstance(text, dict):
        return text.get("en", "")
    return text if isinstance(text, str) else ""


def get_percent_estimates(barcode, ingredient_names):
    doc = db.collection("products").document(barcode).get()
    if doc.exists:
        stored = doc.to_dict().get("percent_estimate")
        if stored and isinstance(stored, list) and len(stored) == len(ingredient_names):
            if any(
                (isinstance(x, str) and "not" in x.lower()) or
                (isinstance(x, dict) and x.get("percent") is None)
                for x in stored
            ):
                pass  # fall through to regenerate
            else:
                return stored

        product_data = get_product_from_openfoodfacts(barcode)
        if not product_data:
            return ["Not Available"] * len(ingredient_names)

        percent_list = []
        for ing in ingredient_names:
            ing_str = ing if isinstance(ing, str) else ing.get("name", "")
            match = next(
                (item.get("percent_estimate") for item in product_data.get("ingredients", [])
                 if isinstance(item, dict) and _get_ingredient_text(item).lower() == ing_str.lower()),
                "Not Available"
            )
            percent_list.append(match if match is not None else "Not Available")

        save_percent_estimate_to_db(barcode, percent_list)
        return percent_list

    # ← ADD THIS — handles new products not yet in Firebase
    return ["Not Available"] * len(ingredient_names)