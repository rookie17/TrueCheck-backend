from firestore import get_ingredient_profile_from_db, save_ingredient_to_db
from utils.llm_client import get_ingredient_profile_from_llm


def enrich_ingredients(ingredients: list) -> list:
    """
    Takes a list of ingredient name strings, returns enriched list
    with LLM-generated profiles. Checks Firestore cache first.
    """
    enriched = []
    for ing in ingredients:
        profile = get_ingredient_profile_from_db(ing)
        if not profile:
            try:
                profile = get_ingredient_profile_from_llm(ing)
                if profile and "error" not in profile:
                    save_ingredient_to_db(ing.lower(), ing, profile)
            except Exception as e:
                profile = {"error": str(e)}
        enriched.append({
            "name": ing,
            "profile": profile
        })
    return enriched