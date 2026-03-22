"""
TrueCheck — Flask Backend
==========================
All Gemini/LLM dependencies removed.
Product scoring is now handled by the local ML pipeline.
"""

from dotenv import load_dotenv
load_dotenv()

import requests # pyright: ignore[reportMissingModuleSource]
from flask import Flask, jsonify, request
from flask_cors import CORS

from firestore import (
    get_product_from_db,
    save_product_to_db,
    get_ingredient_profile_from_db,
    save_ingredient_to_db,
    save_percent_estimate_to_db,
    save_product_rating_to_db,
)
from ml.predict import predict_score, get_model_metadata
from ml.feature_engineering import extract_features
from services.enrichment import enrich_ingredients
from services.percent_estimate import get_percent_estimates

app = Flask(__name__)
CORS(app)


# ─── Helper ───────────────────────────────────────────────────────────────────

def _flatten_ingredients(raw_list: list) -> list[str]:
    """Normalise a mixed list of strings / dicts to plain strings."""
    result = []
    for item in raw_list:
        if isinstance(item, dict):
            name = item.get("text") or item.get("name") or ""
        else:
            name = str(item)
        name = name.strip().lower()
        if name:
            result.append(name)
    return result


# ─── Main route ───────────────────────────────────────────────────────────────

@app.route("/get-complete-product-info", methods=["GET"])
def get_complete_product_info():
    barcode = request.args.get("barcode")
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400

    # ── 1. Check cache ────────────────────────────────────────────────────────
    product_data  = get_product_from_db(barcode)

    if product_data:
        product_name    = product_data["product_name"]
        ingredient_list = product_data["ingredients"]          # list of {name, profile}
        nutrition_data  = product_data["nutrients_per_100g"]
        ingredient_names = _flatten_ingredients(
            [i.get("name") for i in ingredient_list]
        )
    else:
        # ── 2. Fetch from OpenFoodFacts ───────────────────────────────────────
        resp = requests.get(
            f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json",
            timeout=10,
        )
        if resp.status_code != 200:
            return jsonify({"error": "Failed to fetch from OpenFoodFacts"}), 500

        product      = resp.json().get("product", {})
        product_name = product.get("product_name", "Unknown")

        raw_ingredients  = [
            i.get("text") for i in product.get("ingredients", []) if "text" in i
        ]
        ingredient_names = _flatten_ingredients(raw_ingredients)

        nutriments     = product.get("nutriments", {})
        nutrition_data = {k: v for k, v in nutriments.items() if k.endswith("_100g")}

        save_product_to_db(barcode, product_name, ingredient_names, nutrition_data)

    # ── 3. Enrich ingredients (attach profiles) ───────────────────────────────
    final_ingredient_list = []
    for name in ingredient_names:
        profile = get_ingredient_profile_from_db(name)
        if not profile:
            profile = _rule_based_ingredient_profile(name)
            save_ingredient_to_db(name, name, profile)
        final_ingredient_list.append({"name": name, "profile": profile})

    # ── 4. Percent estimates ──────────────────────────────────────────────────
    percent_estimates = get_percent_estimates(barcode, ingredient_names)

    # ── 5. ML Prediction ──────────────────────────────────────────────────────
    product_for_ml = {
        "ingredients":        ingredient_names,
        "nutrients_per_100g": nutrition_data,
    }
    rating = predict_score(product_for_ml)

    # ── 6. Persist ────────────────────────────────────────────────────────────
    save_product_rating_to_db(barcode, rating)
    save_percent_estimate_to_db(barcode, percent_estimates)

    return jsonify({
        "product_name":       product_name,
        "ingredients_profile": final_ingredient_list,
        "nutrients":           nutrition_data,
        "percent_estimate":    percent_estimates,
        "overall_rating":      rating,
    })


# ─── Model info ───────────────────────────────────────────────────────────────

@app.route("/model-info", methods=["GET"])
def model_info():
    """Returns metadata about the currently loaded ML model."""
    meta = get_model_metadata()
    if meta:
        return jsonify(meta)
    return jsonify({
        "status":  "no model trained yet",
        "message": "Run `python -m ml.train` to train the initial model."
    }), 404


@app.route("/trigger-retrain", methods=["POST"])
def trigger_retrain():
    """
    Manually trigger model retraining.
    Protect this endpoint with an API key in production!
    """
    api_key = request.headers.get("X-Admin-Key")
    if api_key != os.getenv("ADMIN_API_KEY", "changeme"):
        return jsonify({"error": "Unauthorized"}), 401

    import threading
    from ml.train import train

    def _retrain():
        train()

    thread = threading.Thread(target=_retrain, daemon=True)
    thread.start()

    return jsonify({"message": "Retraining started in background."})


# ─── Existing utility routes (cleaned up) ────────────────────────────────────

@app.route("/get-product-details", methods=["GET"])
def get_product_details():
    barcode = request.args.get("barcode")
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400

    cached = get_product_from_db(barcode)
    if cached:
        return jsonify({
            "product_name":       cached["product_name"],
            "ingredients":        cached["ingredients"],
            "nutrients_per_100g": cached["nutrients_per_100g"],
        })

    resp = requests.get(
        f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json",
        timeout=10,
    )
    if resp.status_code != 200:
        return jsonify({"error": "Failed to fetch from OpenFoodFacts"}), 500

    product      = resp.json().get("product", {})
    product_name = product.get("product_name", "Unknown")
    ingredients  = _flatten_ingredients(
        [i.get("text") for i in product.get("ingredients", []) if "text" in i]
    )
    nutriments     = product.get("nutriments", {})
    nutrition_data = {k: v for k, v in nutriments.items() if k.endswith("_100g")}

    save_product_to_db(barcode, product_name, ingredients, nutrition_data)
    enriched = enrich_ingredients(ingredients)

    return jsonify({
        "product_name":       product_name,
        "ingredients":        enriched,
        "nutrients_per_100g": nutrition_data,
    })


@app.route("/get-ingredient-profile", methods=["GET"])
def get_ingredient_profile_route():
    name = request.args.get("ingredient_name", "").lower().strip()
    if not name:
        return jsonify({"error": "No ingredient_name provided"}), 400

    profile = get_ingredient_profile_from_db(name)
    if profile:
        return jsonify(profile)

    profile = _rule_based_ingredient_profile(name)
    save_ingredient_to_db(name, name, profile)
    return jsonify(profile)


# ─── Rule-based ingredient profiler (no LLM needed) ──────────────────────────

def _rule_based_ingredient_profile(name: str) -> dict:
    """
    Generate a basic ingredient profile without any API call.
    Categories are inferred from ingredient name keywords.
    """
    name_lower = name.lower()

    # Detect category
    if any(w in name_lower for w in ["sugar", "syrup", "fructose", "glucose", "dextrose"]):
        category, health_flag = "sweetener", "moderate_concern"
    elif any(w in name_lower for w in ["e2", "e1", "benzoate", "sorbate", "nitrate"]):
        category, health_flag = "preservative", "concern"
    elif any(w in name_lower for w in ["color", "colour", "dye", "red 40", "yellow 5"]):
        category, health_flag = "colourant", "concern"
    elif any(w in name_lower for w in ["flour", "wheat", "oat", "rice", "corn", "grain"]):
        category, health_flag = "grain", "generally_safe"
    elif any(w in name_lower for w in ["oil", "fat", "butter", "cream"]):
        category, health_flag = "fat", "moderate"
    elif any(w in name_lower for w in ["milk", "cheese", "whey", "casein", "lactose"]):
        category, health_flag = "dairy", "generally_safe"
    elif any(w in name_lower for w in ["salt", "sodium", "chloride"]):
        category, health_flag = "mineral/salt", "moderate_concern"
    elif any(w in name_lower for w in ["vitamin", "mineral", "iron", "calcium", "zinc"]):
        category, health_flag = "micronutrient", "beneficial"
    elif any(w in name_lower for w in ["fiber", "fibre", "inulin", "pectin", "cellulose"]):
        category, health_flag = "dietary_fiber", "beneficial"
    else:
        category, health_flag = "other", "unknown"

    return {
        "ingredient_name": name,
        "category":        category,
        "health_flag":     health_flag,
        "source":          "rule_based",
    }


import os

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
