from flask import Flask, jsonify, request
import requests
from firestore import get_product_from_db, save_product_to_db, get_ingredient_profile_from_db, save_ingredient_to_db
from utils.openai_client import get_ingredient_details_from_openai

app = Flask(__name__)

from utils.openai_client import get_ingredient_details_from_openai 

@app.route("/test-openai", methods=["GET"])
def test_openai():
    ingredient_name = request.args.get("ingredient_name")
    if not ingredient_name:
        return jsonify({"error": "No ingredient name provided"}), 400

    result = get_ingredient_details_from_openai(ingredient_name)
    return jsonify({"result": result})

@app.route("/get-ingredients", methods=["GET"])
def get_ingredients():
    barcode = request.args.get("barcode")
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400

    product_data = get_product_from_db(barcode)
    if product_data:
        return jsonify(product_data)

    # Not found in DB → fetch from OpenFoodFacts
    url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
    response = requests.get(url)
    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch from OpenFoodFacts"}), 500

    data = response.json()
    product = data.get("product", {})
    product_name = product.get("product_name", "Unknown")
    ingredients = [i.get("text") for i in product.get("ingredients", []) if "text" in i]

    # Save to DB
    save_product_to_db(barcode, product_name, ingredients)

    return jsonify({
        "product_name": product_name,
        "ingredients": ingredients
    })


@app.route("/get-ingredient-profile", methods=["GET"])
def get_ingredient_profile():
    ingredient_name = request.args.get("ingredient_name")
    
    if not ingredient_name:
        return jsonify({"error": "No ingredient name provided"}), 400

    profile = get_ingredient_profile_from_db(ingredient_name)
    if profile:
        return jsonify(profile)
    
    try:
        profile = get_ingredient_details_from_openai(ingredient_name)
        if profile:
            save_ingredient_to_db(ingredient_name.lower(), ingredient_name, profile)
            return jsonify(profile)
        
        else:
            return jsonify({"error":"Failed to get profile from Gemini"}), 500
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    





if __name__ == '__main__':
    app.run(debug=True)
