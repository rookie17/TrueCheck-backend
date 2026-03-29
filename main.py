from dotenv import load_dotenv
load_dotenv()

from flask import Flask, jsonify, request
from firestore import (
    get_product_from_db, save_product_to_db,
    get_ingredient_profile_from_db, save_ingredient_to_db,
    save_percent_estimate_to_db, save_product_rating_to_db
)
from utils.llm_client import get_ingredient_profile_from_llm, get_product_rating_from_llm
from services.enrichment import enrich_ingredients
from services.openfoodfacts_api import get_product_from_openfoodfacts
from services.nutrition_fetcher import fetch_nutrition_from_barcode
from services.percent_estimate import get_percent_estimates

from flask_cors import CORS

app = Flask(__name__)
CORS(app)


@app.route("/get-complete-product-info", methods=["GET"])
def get_complete_product_info():
    barcode = request.args.get("barcode")
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400

    # ---------- 1. LOOK IN DB ----------
    product_data = get_product_from_db(barcode)

    if product_data:
        product_name = product_data.get("product_name", "Unknown")
        cached_ingredients = product_data.get("ingredients", [])  # already [{name, profile}]
        nutrition_data = product_data.get("nutrients_per_100g", {})
        from_cache = True
        off_product_data = None 
    else:
        product = get_product_from_openfoodfacts(barcode)
        if not product:
            return jsonify({"error": "Product not found on OpenFoodFacts"}), 404

        product_name = product.get("product_name", "Unknown")
        raw_ingredient_names = [
            i.get("text") for i in product.get("ingredients", []) if "text" in i
        ]
        nutriments = product.get("nutriments", {})
        nutrition_data = {k: v for k, v in nutriments.items() if k.endswith("_100g")}

        save_product_to_db(barcode, product_name, raw_ingredient_names, nutrition_data)

        cached_ingredients = [{"name": n, "profile": None} for n in raw_ingredient_names]
        from_cache = False
        off_product_data = product

    # ---------- 2. ENRICH INGREDIENTS ----------
    final_ingredient_list = []
    for item in cached_ingredients:
        # If profile already loaded from cache, skip re-fetching
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

    # ---------- 3. GET PERCENT ESTIMATES ----------
    ingredient_names_only = [i.get("name", "") if isinstance(i, dict) else i for i in cached_ingredients]
    percent_estimates = get_percent_estimates(barcode, ingredient_names_only, product_data=off_product_data)

    # ---------- 4. GET RATING ----------
    product_rating = get_product_rating_from_llm(final_ingredient_list, percent_estimates)

    # ---------- 5. SAVE RATING ----------
    save_product_rating_to_db(barcode, product_rating)

    return jsonify({
        "product_name": product_name,
        "ingredients_profile": final_ingredient_list,
        "nutrients": nutrition_data,
        "percent_estimate": percent_estimates,
        "overall_rating": product_rating
    })


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
    ingredients = [i.get("text") for i in product.get("ingredients", []) if "text" in i]
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
    ingredients = [i.get("text") for i in product.get("ingredients", []) if "text" in i]

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