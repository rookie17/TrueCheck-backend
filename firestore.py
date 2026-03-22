"""
Firestore client for TrueCheck.
All Gemini/LLM references removed.
"""

import os
import firebase_admin
from firebase_admin import credentials, firestore

cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
if not cred_path:
    raise RuntimeError("FIREBASE_CREDENTIALS_PATH environment variable not set.")

cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred)

db = firestore.client()


# ─── Products ─────────────────────────────────────────────────────────────────

def get_product_from_db(barcode: str) -> dict | None:
    doc = db.collection("products").document(barcode).get()
    if not doc.exists:
        return None

    data        = doc.to_dict()
    ingredients = data.get("ingredients", [])

    # Attach cached ingredient profiles if stored separately
    ingredient_profiles = []
    for ing in ingredients:
        name    = ing if isinstance(ing, str) else ing.get("name", "")
        profile = get_ingredient_profile_from_db(name.lower())
        if profile:
            ingredient_profiles.append({"name": name, "profile": profile})
        else:
            ingredient_profiles.append({"name": name, "profile": None})

    return {
        "product_name":      data.get("product_name", ""),
        "ingredients":       ingredient_profiles,
        "nutrients_per_100g": data.get("nutrients_per_100g", {}),
        "product_rating":    data.get("product_rating"),
        "percent_estimate":  data.get("percent_estimate"),
    }


def save_product_to_db(barcode: str, product_name: str,
                       ingredient_list: list, nutrition_data: dict = None):
    """Save product with ingredient names only (no profiles)."""
    ingredient_names = [
        ing if isinstance(ing, str) else ing.get("name", "unknown")
        for ing in ingredient_list
    ]
    doc = {"product_name": product_name, "ingredients": ingredient_names}
    if nutrition_data:
        doc["nutrients_per_100g"] = nutrition_data

    db.collection("products").document(barcode).set(doc)


def save_product_rating_to_db(barcode: str, rating_data: dict):
    """
    Save ML prediction result to Firestore.
    rating_data expected shape:
      { "overall_score": float, "method": str, "confidence": str,
        "breakdown": dict, "features": dict }
    """
    db.collection("products").document(barcode).update({
        "product_rating": rating_data
    })


def save_percent_estimate_to_db(barcode: str, percent_list: list):
    db.collection("products").document(barcode).update({
        "percent_estimate": percent_list
    })


# ─── Ingredients ─────────────────────────────────────────────────────────────

def get_ingredient_profile_from_db(ingredient: str) -> dict | None:
    ingredient = ingredient.lower()
    doc = db.collection("ingredients").document(ingredient).get()
    return doc.to_dict() if doc.exists else None


def save_ingredient_to_db(ingredient: str, ingredient_name: str,
                          ingredient_profile: dict):
    ingredient = ingredient.lower()
    db.collection("ingredients").document(ingredient).set({
        "ingredient_name":    ingredient_name,
        "ingredient_profile": ingredient_profile,
    })
