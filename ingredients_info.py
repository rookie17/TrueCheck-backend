from firebase_admin import firestore
from utils.openai_client import get_ingredient_details_from_openai


def get_ingredient_profile(ingredient_name: str):
    db = firestore.client()

    # Check Firestore for existing data in ingredients_profile collection
    doc_ref = db.collection("ingredients_profile").document(ingredient_name)
    doc = doc_ref.get()

    if doc.exists:
        
        return doc.to_dict()


    # If not found in DB, call OpenAI to fetch the details
    ingredient_details = get_ingredient_details_from_openai(ingredient_name)

    # Save the fetched data to Firestore
    doc_ref.set({
        "ingredient_name": ingredient_name,
        "profile": ingredient_details
    })

    # Return the newly fetched ingredient profile
    return {"ingredient_name": ingredient_name, "profile": ingredient_details}

