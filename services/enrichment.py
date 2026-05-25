"""
services/enrichment.py
=======================
Ingredient enrichment — behaviour depends on ANALYSIS_MODE.

ML mode   → returns plain name list; profiles come from rule-based fallback
            or Firestore cache in main.py's loop.
Groq mode → fetches LLM profile per ingredient (checked in main.py's loop).

The actual per-ingredient fetch is centralised in main.py's
_fetch_ingredient_profile() so both modes share one enrichment path.
This file is kept as a thin utility used by secondary endpoints
(/get-product-details, /get-ingredients) that only need names.
"""


def enrich_ingredients(ingredient_names: list) -> list:
    """
    Returns a normalised list of {"name": str} dicts.
    Profiles are resolved lazily in main.py's enrichment loop,
    not here — keeps this function side-effect free.
    """
    return [
        {"name": name.strip().lower()}
        for name in ingredient_names
        if name and str(name).strip()
    ]