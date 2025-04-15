from flask import Flask, jsonify, request
import requests 

import firebase_admin
from firebase_admin import credentials, firestore

cred = credentials.Certificate("truecheck-e1f3b-firebase-adminsdk-fbsvc-fdbd50bdc4.json")
firebase_admin.initialize_app(cred)

db = firestore.client()

app = Flask(__name__)

@app.route("/get-ingredients", methods=["GET"])
def get_ingredients():
    barcode = request.args.get("barcode")
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400

    # Check in Firestore first
    product_ref = db.collection("products").document(barcode)
    product_doc = product_ref.get()

    if product_doc.exists:
        return jsonify(product_doc.to_dict())  # Found in DB

    # If not found → Fetch from OpenFoodFacts
    url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
    response = requests.get(url)

    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch from API"}), 500

    data = response.json()
    product = data.get("product", {})
    product_name = product.get("product_name", "Unknown")
    ingredients = [i.get("text") for i in product.get("ingredients", []) if "text" in i]

    # Save to Firestore
    product_ref.set({
        "product_name": product_name,
        "ingredients": ingredients
    })

    # Return response
    return jsonify({
        "product_name": product_name,
        "ingredients": ingredients
    })



# # Simulated database lookup (replace this with Firebase or your DB)
# def get_product_from_db(barcode):
#     # For now, let's pretend our "DB" only has one product
#     if barcode == "123456":
#         return {"product_name": "Sample Product", "ingredients": ["Water", "Sugar", "Salt"]}
#     return None

# # Function to fetch product details from OpenFoodFacts API
# def get_product_from_openfoodfacts(barcode):
#     url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
#     response = requests.get(url)
#     data = response.json()
    
#     if data.get("product"):
#         product = data["product"]
#         return {
#             "product_name": product.get("product_name", "Unknown Product"),
#             "ingredients": product.get("ingredients_text", "").split(", ")
#         }
#     return {"error": "Product not found in OpenFoodFacts"}


if __name__ == '__main__':
    app.run(debug=True)
