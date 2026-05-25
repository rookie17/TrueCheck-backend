"""
firestore.py
============
"""

import os
import json
import firebase_admin          # type: ignore
from firebase_admin import credentials, firestore  # type: ignore


# ── Init once (guard against double-init in hot-reload / test scenarios) ──────
if not firebase_admin._apps:
    cred_json = os.environ.get("FIREBASE_CREDENTIALS")

    if cred_json:
        try:
            cred_dict = json.loads(cred_json)
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cred_dict)
        except Exception as e:
            raise RuntimeError(f"Failed to parse FIREBASE_CREDENTIALS: {e}") from e
    else:
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
    BUG FIX 2 — Always return a dict from product_rating, never a raw float.

    Old Firestore documents may have product_rating stored as a plain
    float (e.g. 6.5) from before the ML-dict format was introduced.
    _build_rating_response() in main.py calls .get() on this and crashes.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return {
            "overall_score": float(raw),
            "method":        "legacy",
            "confidence":    "low",
            "breakdown":     {},
        }
    if isinstance(raw, dict):
        return raw
    return None   # unexpected type → treat as missing


# ─── Products ─────────────────────────────────────────────────────────────────

def get_product_from_db(barcode: str) -> dict | None:
    """
    Returns the raw product dict from Firestore, or None if not found.

    BUG FIX 4 — ingredients returned as plain strings, not [{name, profile}]
    dicts. main.py's _flatten_ingredients + enrichment loop handles shaping.
    """
    if not barcode or not isinstance(barcode, str):
        return None

    barcode = barcode.strip()
    if "/" in barcode:
        return None

    doc = db.collection("products").document(barcode).get()
    if not doc.exists:
        return None

    data = doc.to_dict()

    # Normalise ingredients: some old docs stored them as dicts
    raw_ingredients = data.get("ingredients", [])
    ingredient_names = []
    for ing in raw_ingredients:
        if isinstance(ing, str):
            ingredient_names.append(ing)
        elif isinstance(ing, dict):
            name = ing.get("name") or ing.get("text") or ""
            if name:
                ingredient_names.append(name)

    return {
        "product_name":       data.get("product_name", ""),
        "ingredients":        ingredient_names,           # always plain strings
        "nutrients_per_100g": data.get("nutrients_per_100g", {}),
        "product_rating":     _normalise_rating(data.get("product_rating")),
        "percent_estimate":   data.get("percent_estimate"),
        "image_url":          data.get("image_url"),
    }


def save_product_to_db(barcode: str, product_name: str,
                       ingredient_list: list, nutrition_data: dict = None,
                       image_url: str = None):
    """
    Save/merge product. Ingredients stored as plain strings only.
    scan_count is incremented on every save.
    """
    ingredient_names = [
        ing if isinstance(ing, str) else ing.get("name", "unknown")
        for ing in ingredient_list
    ]

    doc_ref  = db.collection("products").document(barcode)
    existing = doc_ref.get()
    prev     = existing.to_dict() if existing.exists else {}

    doc_data = {
        "product_name": product_name,
        "ingredients":  ingredient_names,
        "scan_count":   prev.get("scan_count", 0) + 1,
    }

    if nutrition_data:
        doc_data["nutrients_per_100g"] = nutrition_data
    if image_url:
        doc_data["image_url"] = image_url
    if not existing.exists or "created_at" not in prev:
        doc_data["created_at"] = firestore.SERVER_TIMESTAMP

    doc_ref.set(doc_data, merge=True)


def save_product_rating_to_db(barcode: str, rating_data: dict):
    """
    BUG FIX 3 — Use .set(merge=True) instead of .update() so this is safe
    even if the product document doesn't exist yet.
    """
    db.collection("products").document(barcode).set(
        {"product_rating": rating_data}, merge=True
    )


def save_percent_estimate_to_db(barcode: str, percent_list: list):
    """BUG FIX 3 — Same as above; .set(merge=True) instead of .update()."""
    db.collection("products").document(barcode).set(
        {"percent_estimate": percent_list}, merge=True
    )


def save_image_url_to_db(barcode: str, image_url: str):
    db.collection("products").document(barcode).set(
        {"image_url": image_url}, merge=True
    )


def get_product_rating_from_db(barcode: str) -> dict | None:
    doc = db.collection("products").document(barcode).get()
    if doc.exists:
        return _normalise_rating(doc.to_dict().get("product_rating"))
    return None


def save_nutrition_to_db(barcode: str, nutrition_data: dict):
    db.collection("products").document(barcode).set(
        {"nutrients_per_100g": nutrition_data}, merge=True
    )


# ─── Ingredients ──────────────────────────────────────────────────────────────

def get_ingredient_profile_from_db(ingredient) -> dict | None:
    """
    Accepts either a plain string or a dict with 'name'/'text' key.
    Returns None for corrupted/errored Gemini profiles so they get re-fetched.
    """
    if isinstance(ingredient, dict):
        ingredient = ingredient.get("name") or ingredient.get("text") or ""
    if not isinstance(ingredient, str):
        return None

    ingredient = ingredient.strip().lower()
    if not ingredient:
        return None

    doc = db.collection("ingredients").document(ingredient).get()
    if not doc.exists:
        return None

    profile = doc.to_dict()

    # Skip profiles that were saved with an error body
    inner = profile.get("ingredient_profile", {})
    if isinstance(inner, dict) and "error" in inner:
        return None

    return profile


def save_ingredient_to_db(ingredient: str, ingredient_profile: dict):
    """
    BUG FIX 1 — 2-arg signature.

    OLD (buggy): save_ingredient_to_db(name, name, profile)
      → wrapped profile in {"ingredient_name": ..., "ingredient_profile": profile}
      → profile was ALREADY {"ingredient_name": ..., "ingredient_profile": {...}}
      → produced double-nesting in Firestore

    NEW: save_ingredient_to_db(name, profile)
      → profile is the complete Firestore document — .set() directly.
    """
    ingredient = ingredient.strip().lower()
    db.collection("ingredients").document(ingredient).set(ingredient_profile)


# ─── Explore feed ─────────────────────────────────────────────────────────────

def get_recent_products(limit: int = 20, sort_by: str = "recent") -> list[dict]:
    """
    Returns products for an explore/feed endpoint.
    sort_by: "recent" | "most_scanned" | "highly_rated"

    Note: "highly_rated" requires a Firestore composite index on
    product_rating.overall_score. Firestore will log the index URL on
    first use if it's missing.
    """
    ref = db.collection("products")

    try:
        if sort_by == "most_scanned":
            query = ref.order_by("scan_count", direction=firestore.Query.DESCENDING)
        elif sort_by == "highly_rated":
            query = ref.order_by(
                "product_rating.overall_score",
                direction=firestore.Query.DESCENDING
            )
        else:
            query = ref.order_by("created_at", direction=firestore.Query.DESCENDING)

        docs = query.limit(limit).stream()

    except Exception as e:
        print(f"[Firestore] get_recent_products query failed ({sort_by}): {e}")
        return []

    results = []
    for doc in docs:
        data   = doc.to_dict()
        rating = _normalise_rating(data.get("product_rating")) or {}
        score  = rating.get("overall_score") or rating.get("product_score")

        results.append({
            "barcode":      doc.id,
            "product_name": data.get("product_name", "Unknown"),
            "product_score": score,
            "scan_count":   data.get("scan_count", 0),
            "scanned_at":   data.get("created_at").isoformat() if data.get("created_at") else None,
            "image_url":    data.get("image_url"),
        })

    return results