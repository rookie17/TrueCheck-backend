from flask import Flask, jsonify, request
import requests
from firestore import get_product_from_db, save_product_to_db, get_ingredient_profile_from_db, save_ingredient_to_db, save_percent_estimate_to_db, save_product_rating_to_db
from utils.openai_client import get_ingredient_details_from_openai, get_product_rating_from_gemini
from services.enrichment import enrich_ingredients
from services.product_rating import calculate_product_score
from product_rating_algo import processed_product_score
from services.nutrition_fetcher import fetch_nutrition_from_barcode
from services.percent_estimate import get_percent_estimates, save_percent_estimate_to_db


from flask_cors import CORS  # Import CORS

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

@app.route("/get-complete-product-info", methods=["GET"])
def get_complete_product_info():
    barcode = request.args.get("barcode")
    
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400

    # Try to get everything from DB
    product_data = get_product_from_db(barcode)
    
    if product_data:
        product_name = product_data.get("product_name", "Unknown")
        ingredients_profiles = product_data.get("ingredients", [])
        nutrition_data = product_data.get("nutrients_per_100g", {})
        enriched_ingredients = ingredients_profiles  # Set enriched_ingredients from DB directly
    else:
        # If not found in DB, fetch from OpenFoodFacts & enrich
        url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
        response = requests.get(url)
        
        if response.status_code != 200:
            return jsonify({"error": "Failed to fetch from OpenFoodFacts"}), 500

        product = response.json().get("product", {})
        product_name = product.get("product_name", "Unknown")
        raw_ingredients = [i.get("text") for i in product.get("ingredients", []) if "text" in i]
        
        enriched_ingredients = enrich_ingredients(raw_ingredients) if raw_ingredients else []
        
        # Get nutrition data and save to DB
        nutriments = product.get("nutriments", {})
        nutrition_data = {k: v for k, v in nutriments.items() if k.endswith("_100g")}
        
        save_product_to_db(barcode, product_name, enriched_ingredients, nutrition_data)
        
        ingredients_profiles = []

    final_ingredient_list = []
    for ing in enriched_ingredients:
        name = ing["name"] if isinstance(ing, dict) else ing
        
        profile = get_ingredient_profile_from_db(name.lower())
        
        if not profile:
            profile = get_ingredient_details_from_openai(name)
            if profile:
                save_ingredient_to_db(name, name, profile)
        
        final_ingredient_list.append({
            "name": name,
            "profile": profile
        })

    

    # Get percent estimates and save them at the product level
    percent_estimates = get_percent_estimates(barcode, [i["name"] for i in enriched_ingredients])
    save_percent_estimate_to_db(barcode, percent_estimates)  # Save percent estimate at the product level

    product_rating = get_product_rating_from_gemini(final_ingredient_list, percent_estimates)
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

# @app.route("/get-product-score", methods=["GET"])
# def get_product_score():
#     barcode = request.args.get("barcode")
#     if not barcode:
#         return jsonify({"error": "No barcode provided"}), 400

#     product_data = get_product_from_db(barcode)
#     if not product_data:
#         return jsonify({"error": "Product not found"}), 404

#     enriched_ingredients = product_data.get("ingredients", [])
#     result = processed_product_score({
#         "product_name": product_data["product_name"],
#         "ingredients": enriched_ingredients
#     })

    # return jsonify(result)

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

    # Get overall product rating via OpenAI
    result = get_product_rating_from_gemini(ingredients)
    return jsonify(result)

    

if __name__ == '__main__':
    app.run()
