
from firestore import get_ingredient_profile_from_db, save_ingredient_to_db
from utils.openai_client import get_ingredient_details_from_openai

def enrich_ingredients(ingredients):
    enriched = []
    for ing in ingredients:
        profile = get_ingredient_profile_from_db(ing)
        if not profile:
            try:
                profile = get_ingredient_details_from_openai(ing)
                if profile:
                    save_ingredient_to_db(ing.lower(), ing, profile)
            except Exception as e:
                profile = {"error": str(e)}
        enriched.append({
            "name": ing,
            "profile": profile
        })
    return enriched
