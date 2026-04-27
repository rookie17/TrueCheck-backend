"""
firestore.py
============
Firestore client for TrueCheck.

Auth priority:
  1. FIREBASE_CREDENTIALS  — JSON string (production / cloud hosting)
  2. FIREBASE_CREDENTIALS_PATH — file path (local development only)

Fixes applied (v2):
  BUG 1 — save_ingredient_to_db double-nested the profile dict.
           _build_ingredient_profile_fallback() already returns the full
           Firestore document shape, so we now call .set() directly on it
           instead of wrapping it a second time.
           The _fix_nested_profile() bandaid in main.py can stay for old
           documents already in Firestore, but new saves will be clean.

  BUG 2 — get_product_from_db returned product_rating as a raw float for
           products saved before the ML-dict format was introduced.
           _build_rating_response() then called .get() on a float and crashed
           with AttributeError. We now normalise the value here so the rest
           of the app always receives a consistent dict.
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
            # Fix escaped newlines in private key (common when storing in env vars)
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


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _normalise_rating(raw) -> dict | None:
    """
    BUG FIX 2 — Normalise product_rating to always be a dict.

    Old products in Firestore may have been saved with a plain float/int
    (e.g. product_rating: 6.5) before the ML-dict format was introduced.
    Calling .get() on a float crashes _build_rating_response() in main.py.

    We wrap legacy plain-number ratings into the expected dict shape here
    so the rest of the app never has to worry about the type.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        # Legacy plain-number — wrap into standard dict
        return {
            "overall_score": float(raw),
            "method":        "legacy",
            "confidence":    "low",
            "breakdown":     {},
        }
    if isinstance(raw, dict):
        return raw
    # Unexpected type — treat as missing rather than crash
    return None


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
        # BUG FIX 2: always return a dict (or None), never a raw float
        "product_rating":     _normalise_rating(data.get("product_rating")),
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

def get_ingredient_profile_from_db(ingredient) -> dict | None:
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


def save_ingredient_to_db(ingredient: str, ingredient_profile: dict):
    """
    BUG FIX 1 — Save the ingredient profile document to Firestore.

    OLD (buggy) signature:
        save_ingredient_to_db(name, name, profile)
        → wrapped profile in {"ingredient_name": ..., "ingredient_profile": profile}
        → profile was ALREADY {"ingredient_name": ..., "ingredient_profile": {...}}
        → result was double-nested in Firestore

    NEW (fixed) signature:
        save_ingredient_to_db(name, profile)
        → profile is the complete Firestore document — .set() it directly.

    IMPORTANT: Update the two call sites in main.py:
        OLD: save_ingredient_to_db(name, name, profile)
        NEW: save_ingredient_to_db(name, profile)
    """
    ingredient = ingredient.strip().lower()
    db.collection("ingredients").document(ingredient).set(ingredient_profile)
