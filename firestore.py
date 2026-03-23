import os
import firebase_admin
from firebase_admin import credentials, firestore

import json, os
from firebase_admin import credentials, initialize_app

cred_json = os.environ.get("FIREBASE_CREDENTIALS")
if not cred_json:
    raise RuntimeError("FIREBASE_CREDENTIALS_JSON environment variable not set.")

cred_dict = json.loads(cred_json)
cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(cred_dict)
initialize_app(cred)

db = firestore.client()


def get_product_from_db(barcode):
    product_ref = db.collection("products").document(barcode)
    product_doc = product_ref.get()

    if not product_doc.exists:
        return None

    product_data = product_doc.to_dict()
    ingredients = product_data.get("ingredients", [])
    ingredient_profiles = []

    for ingredient in ingredients:
        ingredient_name = ingredient if isinstance(ingredient, str) else ingredient.get("name", "")
        profile = get_ingredient_profile_from_db(ingredient_name.lower())
        if profile:
            ingredient_profiles.append({
                "name": ingredient_name,
                "profile": profile
            })

    return {
        "product_name": product_data.get("product_name", ""),
        "ingredients": ingredient_profiles,
        "nutrients_per_100g": product_data.get("nutrients_per_100g", {})
    }



def save_product_to_db(barcode, product_name, ingredient_list, nutrition_data=None):
    """
    Save product with only ingredient *names* (no profiles).
    """
    # Ensure only names are stored
    ingredient_names = [
        ing if isinstance(ing, str) else ing.get("name", "unknown")
        for ing in ingredient_list
    ]

    doc_data = {
        "product_name": product_name,
        "ingredients": ingredient_names
    }

    if nutrition_data:
        doc_data["nutrients_per_100g"] = nutrition_data

    db.collection("products").document(barcode).set(doc_data)



def get_ingredient_profile_from_db(ingredient):
    ingredient = ingredient.lower()
    ingredient_ref = db.collection("ingredients").document(ingredient)
    ingredient_doc = ingredient_ref.get()
    
    if ingredient_doc.exists:
        return ingredient_doc.to_dict()
    return None

def save_ingredient_to_db(ingredient, ingredient_name, ingredient_profile):
    ingredient = ingredient.lower()
    db.collection("ingredients").document(ingredient).set({
        "ingredient_name": ingredient_name,
        "ingredient_profile": ingredient_profile
    })


def save_product_rating_to_db(barcode, rating_data):
    db.collection("products").document(barcode).update({
        "product_rating": rating_data
    })

from firestore import db 

def save_percent_estimate_to_db(barcode, percent_list):
    product_ref = db.collection("products").document(barcode)
    product_ref.update({"percent_estimate": percent_list})

