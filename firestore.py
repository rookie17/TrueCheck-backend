import os, json
from firebase_admin import credentials, initialize_app, firestore

# Dev: set FIREBASE_CREDENTIALS_PATH=./firebase_config.json in .env
# Prod: set FIREBASE_CREDENTIALS with the raw JSON string
cred_path = os.environ.get("FIREBASE_CREDENTIALS_PATH")
cred_json = os.environ.get("FIREBASE_CREDENTIALS")

if cred_path:
    cred = credentials.Certificate(cred_path)
elif cred_json:
    cred_dict = json.loads(cred_json)
    cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
    cred = credentials.Certificate(cred_dict)
else:
    raise RuntimeError("No Firebase credentials provided. Set FIREBASE_CREDENTIALS_PATH or FIREBASE_CREDENTIALS.")

initialize_app(cred)
db = firestore.client()


def get_product_from_db(barcode):
    """
    Returns the product dict with raw ingredient names (not profiles).
    Profiles are intentionally NOT loaded here — main.py's enrichment
    loop fetches them per-ingredient so partial caches are handled correctly.
    Returns None if the product document doesn't exist.
    """
    product_ref = db.collection("products").document(barcode)
    product_doc = product_ref.get()

    if not product_doc.exists:
        return None

    product_data = product_doc.to_dict()
    ingredients = product_data.get("ingredients", [])

    # Normalise: ingredients are stored as plain strings; return as
    # [{name, profile: None}] so main.py's enrichment loop is uniform.
    normalised = []
    for ing in ingredients:
        name = ing if isinstance(ing, str) else ing.get("name", "")
        if name:
            normalised.append({"name": name, "profile": None})

    return {
        "product_name": product_data.get("product_name", ""),
        "ingredients": normalised,
        "nutrients_per_100g": product_data.get("nutrients_per_100g", {})
    }


def save_product_to_db(barcode, product_name, ingredient_list, nutrition_data=None):
    ingredient_names = [
        ing if isinstance(ing, str) else ing.get("name", "unknown")
        for ing in ingredient_list
    ]

    doc_data = {
        "product_name": product_name,
        "ingredients": ingredient_names
    }

    if nutrition_data:
        doc_data["nutrients_per_100g"] = nutrition_data

    db.collection("products").document(barcode).set(doc_data, merge=True)


def get_ingredient_profile_from_db(ingredient):
    ingredient = ingredient.lower()
    ingredient_ref = db.collection("ingredients").document(ingredient)
    ingredient_doc = ingredient_ref.get()

    if ingredient_doc.exists:
        return ingredient_doc.to_dict()
    return None


def save_ingredient_to_db(ingredient, ingredient_name, ingredient_profile):
    ingredient = ingredient.lower()
    db.collection("ingredients").document(ingredient).set({
        "ingredient_name": ingredient_name,
        "ingredient_profile": ingredient_profile
    })


def save_product_rating_to_db(barcode, rating_data):
    db.collection("products").document(barcode).set(
        {"product_rating": rating_data}, merge=True
    )


def save_percent_estimate_to_db(barcode, percent_list):
    db.collection("products").document(barcode).set(
        {"percent_estimate": percent_list}, merge=True
    )


def get_product_rating_from_db(barcode):
    doc = db.collection("products").document(barcode).get()
    if doc.exists:
        return doc.to_dict().get("product_rating")
    return None


def save_nutrition_to_db(barcode: str, nutrition_data: dict):
    db.collection("products").document(barcode).set(
        {"nutrients_per_100g": nutrition_data},
        merge=True
    )