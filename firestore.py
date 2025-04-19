import firebase_admin
from firebase_admin import credentials, firestore

cred = credentials.Certificate("truecheck-e1f3b-firebase-adminsdk-fbsvc-fdbd50bdc4.json")
firebase_admin.initialize_app(cred)

db = firestore.client()

def get_product_from_db(barcode):
    product_ref = db.collection("products").document(barcode)
    product_doc = product_ref.get()
    if product_doc.exists:
        return product_doc.to_dict()
    return None

def save_product_to_db(barcode, product_name, ingredients):
    db.collection("products").document(barcode).set({
        "product_name": product_name,
        "ingredients": ingredients
    })

def get_ingredient_profile_from_db(ingredient):
    ingredient_ref = db.collection("ingredients").document(ingredient)
    ingredient_doc = ingredient_ref.get()
    if ingredient_doc.exists:
        return ingredient_doc.to_dict()
    return None

def save_ingredient_to_db(ingredient, ingredient_name, ingredient_profile):
    db.collection("ingredients").document(ingredient).set({
        "ingredient_name": ingredient_name,
        "ingredient_profile": ingredient_profile
    })