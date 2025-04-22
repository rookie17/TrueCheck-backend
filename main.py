from flask import Flask, jsonify, request
import requests
from firestore import get_product_from_db, save_product_to_db, get_ingredient_profile_from_db, save_ingredient_to_db
from utils.openai_client import get_ingredient_details_from_openai
from services.enrichment import enrich_ingredients

app = Flask(__name__)

from utils.openai_client import get_ingredient_details_from_openai 

@app.route("/test-openai", methods=["GET"])
def test_openai():
    ingredient_name = request.args.get("ingredient_name")
    if not ingredient_name:
        return jsonify({"error": "No ingredient name provided"}), 400

    result = get_ingredient_details_from_openai(ingredient_name)
    return jsonify({"result": result})

from firestore import (
    get_product_from_db, save_product_to_db,
    get_ingredient_profile_from_db, save_ingredient_to_db
)
from utils.openai_client import get_ingredient_details_from_openai

@app.route("/get-ingredients", methods=["GET"])
def get_ingredients():
    barcode = request.args.get("barcode")
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400

    product_data = get_product_from_db(barcode)
    if product_data:
        # Optionally enrich ingredients here too
        enriched_ingredients = product_data.get("ingredients", [])

        return jsonify({
            "product_name": product_data["product_name"],
            "ingredients": enriched_ingredients
        })

    # Not found in DB → fetch from OpenFoodFacts
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


    # Save basic product info
    save_product_to_db(barcode, product_name, ingredients)

    # Enrich ingredients
    enriched_ingredients = enrich_ingredients(ingredients)

    return jsonify({
        "product_name": product_name,
        "ingredients": enriched_ingredients
    })




@app.route("/get-ingredient-profile", methods=["GET"])
def get_ingredient_profile(ingredient_name):
    ingredient_name = ingredient_name.lower()

    # Check if the ingredient exists in DB
    ingredient_profile = get_ingredient_profile_from_db(ingredient_name)
    
    if ingredient_profile:
        print(f"Ingredient '{ingredient_name}' found in DB.")
        return ingredient_profile
    else:
        print(f"Ingredient '{ingredient_name}' not found in DB. Fetching from API...")

        # Fetch the ingredient details from OpenAI API
        ingredient_profile = get_ingredient_details_from_openai(ingredient_name)
        
        if ingredient_profile:
            # Save to the DB
            print(f"Saving ingredient '{ingredient_name}' to DB.")
            save_ingredient_to_db(ingredient_name, ingredient_name, ingredient_profile)
            return ingredient_profile
        else:
            print(f"Error: Could not fetch data for '{ingredient_name}' from API.")
            return None



if __name__ == '__main__':
    app.run(debug=True)
