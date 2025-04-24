from flask import Flask, jsonify, request
import requests
from firestore import get_product_from_db, save_product_to_db, get_ingredient_profile_from_db, save_ingredient_to_db
from utils.openai_client import get_ingredient_details_from_openai
from services.enrichment import enrich_ingredients
from services.product_rating import calculate_product_score
from product_rating_algo import processed_product_score
from services.nutrition_fetcher import fetch_nutrition_from_barcode


app = Flask(__name__)



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


@app.route("/test-openai", methods=["GET"])
def test_openai():
    ingredient_name = request.args.get("ingredient_name")
    if not ingredient_name:
        return jsonify({"error": "No ingredient name provided"}), 400

    result = get_ingredient_details_from_openai(ingredient_name)
    return jsonify({"result": result})


from services.nutrition_fetcher import fetch_nutrition_from_barcode

@app.route("/get-product-details", methods=["GET"])
def get_product_details():
    barcode = request.args.get("barcode")
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400

    # Check DB first
    product_data = get_product_from_db(barcode)
    if product_data:
        return jsonify({
            "product_name": product_data.get("product_name", "Unknown"),
            "ingredients": product_data.get("ingredients", []),
            "nutrients_per_100g": product_data.get("nutrients_per_100g", {})
        })

    # Fetch from OPFF
    url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
    response = requests.get(url)
    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch from OpenFoodFacts"}), 500

    data = response.json()
    product = data.get("product", {})
    product_name = product.get("product_name", "Unknown")

    # --- INGREDIENTS ---
    ingredients = [i.get("text") for i in product.get("ingredients", []) if "text" in i]
    enriched_ingredients = enrich_ingredients(ingredients) if ingredients else []

    # --- NUTRITION ---
    nutriments = product.get("nutriments", {})
    nutrition_data = {k: v for k, v in nutriments.items() if k.endswith("_100g")}

    # --- SAVE ---
    save_product_to_db(
        barcode=barcode,
        product_name=product_name,
        ingredients=ingredients,
        nutrition_data=nutrition_data
    )

    # --- RESPONSE ---
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
        enriched_ingredients = product_data.get("ingredients", [])
        return jsonify({
            "product_name": product_data["product_name"],
            "ingredients": enriched_ingredients
        })

    url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
    response = requests.get(url)
    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch from OpenFoodFacts"}), 500

    data = response.json()
    product = data.get("product", {})
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

@app.route("/get-product-score", methods=["GET"])
def get_product_score():
    barcode = request.args.get("barcode")
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400

    product_data = get_product_from_db(barcode)
    if not product_data:
        return jsonify({"error": "Product not found"}), 404

    enriched_ingredients = product_data.get("ingredients", [])
    result = processed_product_score({
        "product_name": product_data["product_name"],
        "ingredients": enriched_ingredients
    })

    return jsonify(result)

@app.route("/get-ingredient-profile", methods=["GET"])
def get_ingredient_profile(ingredient_name):
    ingredient_name = ingredient_name.lower()

    ingredient_profile = get_ingredient_profile_from_db(ingredient_name)
    if ingredient_profile:
        return ingredient_profile

    ingredient_profile = get_ingredient_details_from_openai(ingredient_name)
    if ingredient_profile:
        save_ingredient_to_db(ingredient_name, ingredient_name, ingredient_profile)
        return ingredient_profile

    return None

if __name__ == '__main__':
    app.run(debug=True)
