# Gemini and OpenAI removed — ML pipeline handles all scoring now.

def get_ingredient_details_from_openai(ingredient_name: str) -> dict:
    return {
        "source": "rule_based",
        "ingredient_name": ingredient_name
    }

def get_product_rating_from_gemini(ingredients, percent_estimate=None) -> dict:
    return {
        "overall_score": 5.0,
        "method": "rule_based",
        "note": "ML model handles scoring now"
    }