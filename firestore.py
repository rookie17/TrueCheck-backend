import os, json
from firebase_admin import credentials, initialize_app, firestore
from google.cloud.firestore_v1 import Increment

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
        "nutrients_per_100g": product_data.get("nutrients_per_100g", {}),
        "image_url": product_data.get("image_url"),
    }


def save_product_to_db(barcode, product_name, ingredient_list, nutrition_data=None, image_url=None):
    ingredient_names = [
        ing if isinstance(ing, str) else ing.get("name", "unknown")
        for ing in ingredient_list
    ]

    doc_ref = db.collection("products").document(barcode)
    doc = doc_ref.get()
    existing = doc.to_dict() if doc.exists else {}

    doc_data = {
        "product_name": product_name,
        "ingredients": ingredient_names,
        "scan_count": existing.get("scan_count", 0) + 1,
    }

    if nutrition_data:
        doc_data["nutrients_per_100g"] = nutrition_data

    if image_url:
        doc_data["image_url"] = image_url
    if not doc.exists or "created_at" not in existing:
        doc_data["created_at"] = firestore.SERVER_TIMESTAMP

    doc_ref.set(doc_data, merge=True)

def save_image_url_to_db(barcode: str, image_url: str):
    db.collection("products").document(barcode).set(
        {"image_url": image_url}, merge=True
    )

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


def get_recent_products(limit: int = 20, sort_by: str = "recent") -> list[dict]:
    """
    Returns a list of products for the explore feed.
    sort_by: "recent" | "most_scanned" | "highly_rated"
    Note: "highly_rated" requires a Firestore composite index on
    product_rating.product_score — Firestore will log the index creation URL
    on first use if missing.
    """
    ref = db.collection("products")

    try:
        if sort_by == "most_scanned":
            query = ref.order_by("scan_count", direction=firestore.Query.DESCENDING)
        elif sort_by == "highly_rated":
            query = ref.order_by("product_rating.product_score", direction=firestore.Query.DESCENDING)
        else:
            query = ref.order_by("created_at", direction=firestore.Query.DESCENDING)

        docs = query.limit(limit).stream()
    except Exception as e:
        print(f"[Firestore] get_recent_products query failed ({sort_by}): {e}")
        return []

    results = []
    for doc in docs:
        data = doc.to_dict()
        rating = data.get("product_rating", {}) or {}
        score = rating.get("product_score") or rating.get("overall_score")

        results.append({
            "barcode": doc.id,
            "product_name": data.get("product_name", "Unknown"),
            "product_score": score,
            "scan_count": data.get("scan_count", 0),
            "scanned_at": data.get("created_at").isoformat() if data.get("created_at") else None,
            "image_url": data.get("image_url"),
        })

    return results