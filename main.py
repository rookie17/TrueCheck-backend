from dotenv import load_dotenv
load_dotenv()

from flask import Flask, jsonify, request
from firestore import (
    get_product_from_db, save_product_to_db,
    get_ingredient_profile_from_db, save_ingredient_to_db,
    save_percent_estimate_to_db, save_product_rating_to_db,
    get_product_rating_from_db
)
from utils.llm_client import get_ingredient_profile_from_llm, get_product_rating_from_llm
from services.enrichment import enrich_ingredients
from services.openfoodfacts_api import get_product_from_openfoodfacts
from services.nutrition_fetcher import fetch_nutrition_from_barcode
from services.percent_estimate import get_percent_estimates
from services.upcitemdb import get_product_name_from_barcode
from services.scrapers.bigbasket import get_product_by_name as bb_get_product_by_name
from utils.ingredient_utils import extract_ingredient_text

from flask_cors import CORS

app = Flask(__name__)
CORS(app)


def _parse_ingredients_from_raw(raw: str) -> list[str]:
    """
    Split a raw ingredients string (from BB or elsewhere) into a list of names.
    Splits on commas, strips parens content and percentages, cleans whitespace.
    """
    import re
    # Remove percentage annotations like (35.6%)
    cleaned = re.sub(r"\(\d+\.?\d*%\)", "", raw)
    # Split on comma
    parts = [p.strip() for p in cleaned.split(",")]
    # Remove empty, very short, or numeric-only parts
    return [p for p in parts if len(p) > 1 and not p.replace(".", "").isdigit()]


@app.route("/get-complete-product-info", methods=["GET"])
def get_complete_product_info():
    barcode = request.args.get("barcode")
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400

    # ---------- 1. LOOK IN DB ----------
    product_data = get_product_from_db(barcode)

    if product_data:
        product_name = product_data.get("product_name", "Unknown")
        cached_ingredients = product_data.get("ingredients", [])
        nutrition_data = product_data.get("nutrients_per_100g", {})
        off_product_data = None

    else:
        # ---------- 2. TRY OPENFOODFACTS ----------
        off_product = get_product_from_openfoodfacts(barcode)

        product_name = None
        raw_ingredient_names = []
        nutrition_data = {}
        off_product_data = None

        if off_product:
            product_name = off_product.get("product_name", "Unknown")
            raw_ingredient_names = [
                extract_ingredient_text(i) for i in off_product.get("ingredients", [])
                if extract_ingredient_text(i)
            ]
            nutriments = off_product.get("nutriments", {})
            nutrition_data = {k: v for k, v in nutriments.items() if k.endswith("_100g")}
            off_product_data = off_product

        # ---------- 3. BB FALLBACK (no OFf result, or OFf has no ingredients) ----------
        if not off_product or not raw_ingredient_names:
            # Need a product name to search BB
            if not product_name or product_name == "Unknown":
                product_name = get_product_name_from_barcode(barcode)

            if product_name:
                bb_data = bb_get_product_by_name(product_name)
                if bb_data and bb_data.get("ingredients_raw"):
                    raw_ingredient_names = _parse_ingredients_from_raw(
                        bb_data["ingredients_raw"]
                    )
                    if not nutrition_data and bb_data.get("nutrition"):
                        nutrition_data = bb_data["nutrition"]
                    # Use BB product name only if we had nothing from OFf
                    if not product_name or product_name == "Unknown":
                        product_name = bb_data.get("product_name", "Unknown")

        if not raw_ingredient_names:
            return jsonify({
                "error": "Product not found or ingredients unavailable",
                "product_name": product_name or "Unknown"
            }), 404

        product_name = product_name or "Unknown"
        save_product_to_db(barcode, product_name, raw_ingredient_names, nutrition_data)
        cached_ingredients = [{"name": n, "profile": None} for n in raw_ingredient_names]

    # ---------- 4. ENRICH INGREDIENTS ----------
    final_ingredient_list = []
    for item in cached_ingredients:
        if isinstance(item, dict) and item.get("profile"):
            final_ingredient_list.append(item)
            continue

        name_str = item.get("name") if isinstance(item, dict) else str(item)
        name_str = str(name_str).strip().lower()
        if not name_str:
            continue

        profile_doc = get_ingredient_profile_from_db(name_str)
        if not profile_doc:
            profile_doc = get_ingredient_profile_from_llm(name_str)
            if profile_doc and "error" not in profile_doc:
                save_ingredient_to_db(name_str, name_str, profile_doc)

        final_ingredient_list.append({"name": name_str, "profile": profile_doc})

    # ---------- 5. PERCENT ESTIMATES ----------
    ingredient_names_only = [
        i.get("name", "") if isinstance(i, dict) else i
        for i in cached_ingredients
    ]
    percent_estimates = get_percent_estimates(
        barcode, ingredient_names_only, product_data=off_product_data
    )

    # ---------- 6. RATING ----------
    product_rating = get_product_rating_from_db(barcode)
    if not product_rating:
        product_rating = get_product_rating_from_llm(final_ingredient_list, percent_estimates)
        save_product_rating_to_db(barcode, product_rating)

    return jsonify({
        "product_name": product_name,
        "ingredients_profile": final_ingredient_list,
        "nutrients": nutrition_data,
        "percent_estimate": percent_estimates,
        "overall_rating": product_rating
    })


# All other routes remain unchanged below
@app.route("/test-nutrition", methods=["GET"])
def test_nutrition():
    barcode = request.args.get("barcode")
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400

    result = fetch_nutrition_from_barcode(barcode)
    if result is None:
        return jsonify({"message": "No nutrition data found or saved."}), 404

    return jsonify({
        "message": "Nutrition data saved successfully.",
        "data": result
    })


@app.route("/test-llm", methods=["GET"])
def test_llm():
    ingredient_name = request.args.get("ingredient_name")
    if not ingredient_name:
        return jsonify({"error": "No ingredient name provided"}), 400

    result = get_ingredient_profile_from_llm(ingredient_name)
    return jsonify({"result": result})


@app.route("/get-product-details", methods=["GET"])
def get_product_details():
    barcode = request.args.get("barcode")
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400

    product_data = get_product_from_db(barcode)
    if product_data:
        return jsonify({
            "product_name": product_data.get("product_name", "Unknown"),
            "ingredients": product_data.get("ingredients", []),
            "nutrients_per_100g": product_data.get("nutrients_per_100g", {})
        })

    product = get_product_from_openfoodfacts(barcode)
    if not product:
        return jsonify({"error": "Product not found on OpenFoodFacts"}), 404

    product_name = product.get("product_name", "Unknown")
    ingredients = [
        extract_ingredient_text(i) for i in product.get("ingredients", [])
        if extract_ingredient_text(i)
    ]
    nutriments = product.get("nutriments", {})
    nutrition_data = {k: v for k, v in nutriments.items() if k.endswith("_100g")}

    enriched_ingredients = enrich_ingredients(ingredients) if ingredients else []
    save_product_to_db(barcode, product_name, ingredients, nutrition_data)

    return jsonify({
        "product_name": product_name,
        "ingredients": enriched_ingredients,
        "nutrients_per_100g": nutrition_data
    })


@app.route("/get-ingredients", methods=["GET"])
def get_ingredients():
    barcode = request.args.get("barcode")
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400

    product_data = get_product_from_db(barcode)
    if product_data:
        return jsonify({
            "product_name": product_data["product_name"],
            "ingredients": product_data.get("ingredients", [])
        })

    product = get_product_from_openfoodfacts(barcode)
    if not product:
        return jsonify({"error": "Product not found on OpenFoodFacts"}), 404

    product_name = product.get("product_name", "Unknown")
    ingredients = [
        extract_ingredient_text(i) for i in product.get("ingredients", [])
        if extract_ingredient_text(i)
    ]

    if not ingredients:
        return jsonify({
            "product_name": product_name,
            "ingredients": [],
            "note": "Ingredients data not available for this barcode on OpenFoodFacts."
        })

    save_product_to_db(barcode, product_name, ingredients)
    enriched_ingredients = enrich_ingredients(ingredients)

    return jsonify({
        "product_name": product_name,
        "ingredients": enriched_ingredients
    })


@app.route("/get-ingredient-profile", methods=["GET"])
def get_ingredient_profile():
    ingredient_name = request.args.get("ingredient_name")
    if not ingredient_name:
        return jsonify({"error": "No ingredient_name provided"}), 400

    ingredient_name = ingredient_name.lower()

    profile = get_ingredient_profile_from_db(ingredient_name)
    if profile:
        return jsonify(profile)

    profile = get_ingredient_profile_from_llm(ingredient_name)
    if profile and "error" not in profile:
        save_ingredient_to_db(ingredient_name, ingredient_name, profile)
        return jsonify(profile)

    return jsonify({"error": "Could not retrieve ingredient profile"}), 500


@app.route("/get-overall-product-rating", methods=["GET"])
def get_overall_product_rating():
    barcode = request.args.get("barcode")
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400

    product_data = get_product_from_db(barcode)
    if not product_data:
        return jsonify({"error": "Product not found in DB"}), 404

    ingredients = product_data.get("ingredients")
    if not ingredients:
        return jsonify({"error": "No ingredients found. Please enrich first."}), 400

    result = get_product_rating_from_llm(ingredients, ["not avail"] * len(ingredients))
    return jsonify(result)


if __name__ == "__main__":
    app.run()