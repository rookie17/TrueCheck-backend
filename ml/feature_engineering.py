"""
Feature Engineering for TrueCheck ML Pipeline
Converts raw product data into a numeric feature vector.
"""

import re
import numpy as np
TRANSLATION_MAP = {
    "sucre": "sugar",
    "huile de palme": "palm oil",
    "lait": "milk",
    "lait écrémé en poudre": "skimmed milk powder",
    "noisettes": "hazelnuts",
    "cacao": "cocoa",
    "cacao maigre": "cocoa",
    "émulsifiant": "emulsifier",
    "émulsifiants": "emulsifier",
    "lécithines": "lecithin",
    "lécithines de soja": "soy lecithin",
    "vanilline": "vanillin",
    "sel": "salt",
    "huile de colza": "rapeseed oil",
    "farine de blé": "wheat flour",
    "farine de blé complet": "whole wheat flour",
    "sirop de glucose": "glucose syrup",
    "amidon de blé": "wheat starch",
    "arômes": "flavour",
}

# ─── Additive / Processing Markers ───────────────────────────────────────────

ARTIFICIAL_SWEETENERS = {
    "aspartame", "sucralose", "saccharin", "acesulfame", "stevia extract",
    "neotame", "advantame", "acesulfame potassium", "acesulfame-k",
}

PRESERVATIVES = {
    "sodium benzoate", "potassium sorbate", "sodium nitrate", "sodium nitrite",
    "bha", "bht", "tbhq", "calcium propionate", "sodium propionate",
    "sulfur dioxide", "sulphur dioxide",
}

HARMFUL_ADDITIVES = {
    "high fructose corn syrup", "hfcs", "hydrogenated oil",
    "partially hydrogenated", "trans fat", "monosodium glutamate", "msg",
    "carrageenan", "titanium dioxide", "red 40", "yellow 5", "yellow 6",
    "blue 1", "blue 2", "red 3",
}

# E-number pattern (E100–E999)
E_NUMBER_PATTERN = re.compile(r'\be\d{3,4}\b', re.IGNORECASE)


# ─── Core Feature Extractor ───────────────────────────────────────────────────

def extract_features(product: dict) -> dict:
    nutrients = product.get("nutrients_per_100g", {}) or {}
    # print("RAW NUTRIENTS:", nutrients)

    raw_ingredients = product.get("ingredients", []) or []

    ingredient_names = []
    for ing in raw_ingredients:
        if isinstance(ing, dict):
            name = ing.get("name") or ing.get("text") or ""
        else:
            name = str(ing)

        name = name.lower().strip()
        name = TRANSLATION_MAP.get(name, name)

        ingredient_names.append(name)

    ingredient_text = " ".join(ingredient_names)

    def get_nutrient(key: str, fallback: float = 0.0) -> float:
        for candidate in [key, key.replace("_100g", ""), f"{key}_100g"]:
            val = nutrients.get(candidate)
            if val is not None:
                try:
                    return float(val)
                except:
                    pass
        return fallback

    energy = (
        get_nutrient("energy-kcal_100g") or
        get_nutrient("energy_100g") or
        0.0
    )

    sugars = get_nutrient("sugars_100g", 0.0)
    fat = get_nutrient("fat_100g", 0.0)
    saturated = get_nutrient("saturated-fat_100g", 0.0)
    sodium = get_nutrient("sodium_100g", 0.0)
    fiber = get_nutrient("fiber_100g", 0.0)
    proteins = get_nutrient("proteins_100g", 0.0)
    carbs = get_nutrient("carbohydrates_100g", 0.0)
    salt = get_nutrient("salt_100g", sodium * 2.5)

    ingredient_count = len(ingredient_names)

    additive_count = len(E_NUMBER_PATTERN.findall(ingredient_text))

    has_artificial_sweetener = int(any(sw in ingredient_text for sw in ARTIFICIAL_SWEETENERS))
    has_preservatives = int(any(p in ingredient_text for p in PRESERVATIVES))
    has_harmful_additives = int(any(h in ingredient_text for h in HARMFUL_ADDITIVES))

    processed_score = min(
        10.0,
        (ingredient_count * 0.3) + (additive_count * 1.5) + (has_harmful_additives * 2.0)
    )

    sugar_to_carb_ratio = (sugars / carbs) if carbs > 0 else 0.0
    sat_fat_to_fat_ratio = (saturated / fat) if fat > 0 else 0.0

    # ── Calorie bucket ─────────────────────────
    if energy < 150:
        calorie_bucket = 0
    elif energy < 350:
        calorie_bucket = 1
    else:
        calorie_bucket = 2

    # ── Smart Health Indicators (FIXED ✅) ──────
    if sugars < 5:
        sugar_level = 0
    elif sugars < 15:
        sugar_level = 1
    else:
        sugar_level = 2

    if salt < 0.3:
        salt_level = 0
    elif salt < 1.5:
        salt_level = 1
    else:
        salt_level = 2

    if fiber > 5:
        fiber_quality = 2
    elif fiber > 2:
        fiber_quality = 1
    else:
        fiber_quality = 0

    # ── FINAL FEATURES ─────────────────────────
    features = {
        "energy_100g": energy,
        "sugars_100g": sugars,
        "fat_100g": fat,
        "saturated_fat_100g": saturated,
        "sodium_100g": sodium,
        "salt_100g": salt,
        "fiber_100g": fiber,
        "proteins_100g": proteins,
        "carbohydrates_100g": carbs,

        "ingredient_count": ingredient_count,
        "additive_count": additive_count,
        "has_artificial_sweetener": has_artificial_sweetener,
        "has_preservatives": has_preservatives,
        "has_harmful_additives": has_harmful_additives,
        "processed_score": processed_score,

        "sugar_to_carb_ratio": round(sugar_to_carb_ratio, 4),
        "sat_fat_to_fat_ratio": round(sat_fat_to_fat_ratio, 4),
        "calorie_bucket": calorie_bucket,

        # ✅ NEW FEATURES
        "sugar_level": sugar_level,
        "salt_level": salt_level,
        "fiber_quality": fiber_quality,
    }

    return features


FEATURE_COLUMNS = [
    "energy_100g", "sugars_100g", "fat_100g", "saturated_fat_100g",
    "sodium_100g", "salt_100g", "fiber_100g", "proteins_100g",
    "carbohydrates_100g", "ingredient_count", "additive_count",
    "has_artificial_sweetener", "has_preservatives", "has_harmful_additives",
    "processed_score", "sugar_to_carb_ratio", "sat_fat_to_fat_ratio",
    "calorie_bucket","sugar_level",
"salt_level",
"fiber_quality",
]


def features_to_vector(feature_dict: dict) -> np.ndarray:
    """Convert feature dict → ordered numpy array matching FEATURE_COLUMNS."""
    return np.array([feature_dict.get(col, 0.0) for col in FEATURE_COLUMNS], dtype=np.float32)
