"""
firestore.py
============
Firestore client for TrueCheck.

Auth priority:
  1. FIREBASE_CREDENTIALS  — JSON string (production / cloud hosting)
  2. FIREBASE_CREDENTIALS_PATH — file path (local development only)
"""

import os
import json
import firebase_admin  # type: ignore
from firebase_admin import credentials, firestore  # type: ignore


# ── Init once — guarded against double-init ───────────────────────────────────
if not firebase_admin._apps:
    cred_json = os.environ.get("FIREBASE_CREDENTIALS")

    if cred_json:
        # Production: read credentials from JSON string env var
        try:
            cred_dict = json.loads(cred_json)
            # Fix escaped newlines in private key (common when storing JSON in env vars)
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cred_dict)
        except Exception as e:
            raise RuntimeError(f"Failed to parse FIREBASE_CREDENTIALS: {e}") from e
    else:
        # Local dev: read credentials from file path
        cred_path = os.environ.get("FIREBASE_CREDENTIALS_PATH")
        if not cred_path:
            raise RuntimeError(
                "Firebase credentials not configured.\n"
                "  Production : set FIREBASE_CREDENTIALS as a JSON string.\n"
                "  Local dev  : set FIREBASE_CREDENTIALS_PATH to your serviceAccountKey.json."
            )
        cred = credentials.Certificate(cred_path)

    firebase_admin.initialize_app(cred)

db = firestore.client()


# ─── Products ─────────────────────────────────────────────────────────────────

def get_product_from_db(barcode: str) -> dict | None:
    if not barcode or not isinstance(barcode, str):
        return None

    barcode = barcode.strip()

    if "/" in barcode:
        return None

    doc = db.collection("products").document(barcode).get()

    if not doc.exists:
        return None

    data = doc.to_dict()

    return {
        "product_name":       data.get("product_name", ""),
        "ingredients":        data.get("ingredients", []),
        "nutrients_per_100g": data.get("nutrients_per_100g", {}),
        "product_rating":     data.get("product_rating"),
        "percent_estimate":   data.get("percent_estimate"),
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
    db.collection("products").document(barcode).update({
        "product_rating": rating_data
    })


def save_percent_estimate_to_db(barcode: str, percent_list: list):
    db.collection("products").document(barcode).update({
        "percent_estimate": percent_list
    })


# ─── Ingredients ─────────────────────────────────────────────────────────────

def get_ingredient_profile_from_db(ingredient):
    # Handle dict input
    if isinstance(ingredient, dict):
        ingredient = ingredient.get("name") or ingredient.get("text") or ""

    if not isinstance(ingredient, str):
        return None

    ingredient = ingredient.strip().lower()

    if not ingredient:
        return None

    ingredient_ref = db.collection("ingredients").document(ingredient)
    ingredient_doc = ingredient_ref.get()

    if ingredient_doc.exists:
        profile = ingredient_doc.to_dict()

        # Skip corrupted Gemini data
        if "ingredient_profile" in profile:
            inner = profile["ingredient_profile"]
            if isinstance(inner, dict) and "error" in inner:
                return None

        return profile

    return None


def save_ingredient_to_db(ingredient: str, ingredient_name: str,
                          ingredient_profile: dict):
    ingredient = ingredient.lower()
    db.collection("ingredients").document(ingredient).set({
        "ingredient_name":    ingredient_name,
        "ingredient_profile": ingredient_profile,
    })
