"""
utils/llm_client.py
====================
Groq/LLaMA wrappers — only imported when ANALYSIS_MODE=groq.

Two functions:
  get_ingredient_profile_from_llm(name)         → per-ingredient health profile
  get_product_rating_from_llm(ingredients, pct) → overall product rating

Both return parsed JSON dicts, or {"error": ...} on failure.
main.py checks for "error" keys and falls back gracefully.
"""

import os
from groq import Groq
from utils.clean_json_output import parse_cleaned_json

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

_MODEL = "llama-3.3-70b-versatile"


def get_ingredient_profile_from_llm(ingredient_name: str) -> dict:
    """
    Uses Groq/LLaMA to generate a health profile for a single ingredient.
    Returns parsed JSON dict or {"error": ...} on failure.

    The returned dict is the inner profile (not the Firestore wrapper).
    main.py wraps it into {"ingredient_name": name, "ingredient_profile": ...}
    before saving to Firestore.
    """
    ingredient_name = ingredient_name.strip().lower()

    try:
        with open("utils/system_prompt.txt", "r") as f:
            system_prompt = f.read()

        response = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system",  "content": system_prompt},
                {"role": "user",    "content": ingredient_name},
            ],
            temperature=0.4,
        )

        return parse_cleaned_json(response.choices[0].message.content)

    except Exception as e:
        return {"error": f"LLM ingredient profile failed: {str(e)}"}


def get_product_rating_from_llm(ingredients: list, percent_estimate: list) -> dict:
    """
    Uses Groq/LLaMA to generate an overall product health rating.
    Returns parsed JSON dict or {"error": ...} on failure.

    ingredients     — list of {"name": str, "profile": dict}
    percent_estimate — list aligned to ingredients
    """
    # Pad / trim percent_estimate to match ingredient count
    n = len(ingredients)
    if len(percent_estimate) < n:
        percent_estimate = percent_estimate + ["not avail"] * (n - len(percent_estimate))
    percent_estimate = percent_estimate[:n]

    try:
        with open("utils/product_rating_prompt.txt", "r") as f:
            system_prompt = f.read()

        full_prompt = (
            f"ingredients = {ingredients}\n"
            f"percent_estimate = {percent_estimate}"
        )

        response = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": full_prompt},
            ],
            temperature=0.2,
        )

        return parse_cleaned_json(response.choices[0].message.content)

    except Exception as e:
        return {"error": f"LLM product rating failed: {str(e)}"}