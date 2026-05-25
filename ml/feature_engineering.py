"""
Feature Engineering for TrueCheck ML Pipeline  ·  v2
======================================================
Converts raw product data into a numeric feature vector.

Changes vs v1:
  - Removed print("FEATURES:", ...) debug log — was spamming production logs
    on every single product scan
  - Added Indian-specific harmful ingredient detection
    (maida, dalda, vanaspati, palm olein — extremely common in Indian
    packaged foods and strongly correlated with poor health scores)
  - Added NOVA ultra-processing markers for a proxy NOVA classification
  - Added healthy fat / whole grain / natural food detection
  - Added protein-to-calorie ratio (important quality signal — a protein bar
    and a biscuit can have the same calorie count but very different quality)
  - Added free_sugar_flag: detects added-sugar keywords appearing early in
    the ingredient list (ingredient order = descending weight in most markets)
  - Added allergen_count: number of common allergens present
  - Expanded E-number map with more common additives
  - Fixed FEATURE_COLUMNS indentation
  - All new features are appended at the END of FEATURE_COLUMNS so that
    models trained on v1 features still load without error (new features
    default to 0.0 via features_to_vector). Retrain after deploying.
"""

import re
import numpy as np


# ─── Translation maps ─────────────────────────────────────────────────────────

TRANSLATION_MAP = {
    # French
    "sucre":                    "sugar",
    "huile de palme":           "palm oil",
    "lait":                     "milk",
    "lait écrémé en poudre":    "skimmed milk powder",
    "noisettes":                "hazelnuts",
    "cacao":                    "cocoa",
    "cacao maigre":             "cocoa",
    "émulsifiant":              "emulsifier",
    "émulsifiants":             "emulsifier",
    "lécithines":               "lecithin",
    "lécithines de soja":       "soy lecithin",
    "vanilline":                "vanillin",
    "sel":                      "salt",
    "huile de colza":           "rapeseed oil",
    "farine de blé":            "wheat flour",
    "farine de blé complet":    "whole wheat flour",
    "sirop de glucose":         "glucose syrup",
    "amidon de blé":            "wheat starch",
    "arômes":                   "flavour",
    # Hindi / Hinglish (common on Indian product labels)
    "maida":                    "refined wheat flour",
    "dalda":                    "hydrogenated vegetable oil",
    "vanaspati":                "hydrogenated vegetable oil",
    "shakkar":                  "sugar",
    "namak":                    "salt",
    "tel":                      "oil",
    "atta":                     "whole wheat flour",
    "besan":                    "chickpea flour",
}

E_NUMBER_MAP = {
    # Preservatives
    "e200": "sorbic acid",
    "e202": "potassium sorbate",
    "e211": "sodium benzoate",
    "e220": "sulphur dioxide",
    "e250": "sodium nitrite",
    "e251": "sodium nitrate",
    # Antioxidants
    "e320": "bha",
    "e321": "bht",
    # Sweeteners
    "e950": "acesulfame potassium",
    "e951": "aspartame",
    "e955": "sucralose",
    "e960": "steviol glycosides",
    # Emulsifiers / thickeners
    "e322": "lecithin",
    "e415": "xanthan gum",
    "e412": "guar gum",
    "e471": "mono- and diglycerides",
    # Colours (many flagged as harmful)
    "e102": "tartrazine",
    "e110": "sunset yellow",
    "e122": "carmoisine",
    "e124": "ponceau 4r",
    "e129": "allura red",
    # Starch / bulking
    "e1422": "modified starch",
    "e1442": "modified starch",
    # Acidity regulators
    "e260": "acetic acid",
    "e330": "citric acid",
    "e331": "sodium citrate",
}


# ─── Ingredient classifier sets ───────────────────────────────────────────────

ARTIFICIAL_SWEETENERS = {
    "aspartame", "sucralose", "saccharin", "acesulfame", "stevia extract",
    "neotame", "advantame", "acesulfame potassium", "acesulfame-k",
    "steviol glycosides", "cyclamate", "erythritol", "sorbitol", "maltitol",
    "xylitol", "isomalt",
}

PRESERVATIVES = {
    "sodium benzoate", "potassium sorbate", "sodium nitrate", "sodium nitrite",
    "bha", "bht", "tbhq", "calcium propionate", "sodium propionate",
    "sulfur dioxide", "sulphur dioxide", "sorbic acid", "nisin",
}

HARMFUL_ADDITIVES = {
    # Trans fats / hydrogenated oils
    "high fructose corn syrup", "hfcs", "hydrogenated oil",
    "partially hydrogenated", "trans fat", "hydrogenated vegetable oil",
    "dalda", "vanaspati",
    # Flavour enhancers
    "monosodium glutamate", "msg",
    # Controversial additives
    "carrageenan", "titanium dioxide",
    # Artificial colours
    "red 40", "yellow 5", "yellow 6", "blue 1", "blue 2", "red 3",
    "tartrazine", "sunset yellow", "carmoisine", "ponceau", "allura red",
}

# ── NEW: Indian-specific harmful ingredients ──────────────────────────────────
INDIAN_HARMFUL = {
    # Refined flour — nutritionally empty, high glycaemic index
    "maida", "refined wheat flour", "refined flour",
    # Hydrogenated fats — primary source of trans fats in Indian snacks
    "vanaspati", "dalda", "hydrogenated vegetable oil",
    "partially hydrogenated vegetable oil",
    # Palm-based oils (high in saturated fat, environmentally controversial)
    "palm olein", "palm kernel oil", "interesterified palm oil",
    # High-sugar syrups common in Indian sweets / drinks
    "glucose syrup", "corn syrup", "liquid glucose",
}

# ── NEW: NOVA Group 4 ultra-processing markers ────────────────────────────────
# Presence of ≥2 of these strongly suggests NOVA Group 4 (ultra-processed)
NOVA4_MARKERS = {
    "flavour", "artificial flavour", "natural flavour", "flavouring",
    "colour", "artificial colour", "food colour",
    "emulsifier", "stabiliser", "thickener", "humectant", "anti-caking agent",
    "raising agent", "modified starch", "hydrolysed protein",
    "maltodextrin", "dextrose", "fructose", "invert sugar",
    "high fructose corn syrup", "glucose syrup",
    "mono- and diglycerides", "lecithin",
    "sodium stearoyl lactylate", "carrageenan",
}

# ── NEW: Healthy ingredient markers ──────────────────────────────────────────
HEALTHY_FATS = {
    "olive oil", "extra virgin olive oil", "avocado oil",
    "flaxseed", "linseed", "chia seed", "walnuts", "almonds",
    "sunflower oil", "rapeseed oil", "canola oil",
    "omega-3", "dha", "epa",
}

WHOLE_GRAINS = {
    "whole wheat", "whole wheat flour", "whole grain", "oats", "oat flour",
    "brown rice", "quinoa", "barley", "rye", "millet", "sorghum",
    "buckwheat", "atta", "besan",   # atta & besan are Indian whole grain flours
}

NATURAL_FOODS = {
    "water", "milk", "egg", "eggs", "butter", "cream", "cheese",
    "fruit", "vegetable", "tomato", "onion", "garlic", "ginger",
    "lemon", "lime", "vinegar", "honey", "maple syrup",
    "nuts", "seeds", "legumes", "lentils", "chickpeas", "beans",
}

# ── NEW: Allergen set ─────────────────────────────────────────────────────────
ALLERGENS = {
    "gluten", "wheat", "barley", "rye", "oats",
    "milk", "lactose", "dairy", "cream", "butter", "cheese", "whey", "casein",
    "egg", "eggs",
    "peanut", "peanuts", "groundnut",
    "tree nuts", "almonds", "walnuts", "cashews", "pistachios", "hazelnuts",
    "soy", "soya", "soybean",
    "fish", "shellfish", "shrimp", "prawn", "crab", "lobster",
    "sesame", "mustard", "celery", "lupin", "molluscs", "sulphite",
}

# ── NEW: Free / added sugar keywords ─────────────────────────────────────────
FREE_SUGAR_KEYWORDS = {
    "sugar", "sucrose", "glucose", "fructose", "dextrose", "maltose",
    "high fructose corn syrup", "corn syrup", "liquid glucose",
    "invert sugar", "brown sugar", "cane sugar", "raw sugar",
    "honey", "maple syrup", "agave", "molasses", "jaggery",
    "glucose syrup", "treacle",
}

# E-number pattern (E100–E9999)
E_NUMBER_PATTERN = re.compile(r'\be\d{3,4}\b', re.IGNORECASE)

# ── E-number category classifiers ─────────────────────────────────────────────
HARMFUL_E_NUMBERS = {
    # Nitrites / nitrates
    "e249", "e250", "e251", "e252",
    # Synthetic antioxidants
    "e310", "e311", "e312", "e320", "e321",
    # Azo dyes (hyperactivity-linked)
    "e102", "e104", "e110", "e122", "e123", "e124", "e127", "e128",
    "e129", "e131", "e132", "e133",
    # Controversial
    "e171",   # titanium dioxide
    "e621",   # MSG
}

HARMFUL_E_PATTERN = re.compile(
    r'\b(' + '|'.join(HARMFUL_E_NUMBERS) + r')\b', re.IGNORECASE
)


# ─── Core Feature Extractor ───────────────────────────────────────────────────

def extract_features(product: dict) -> dict:
    nutrients        = product.get("nutrients_per_100g", {}) or {}
    raw_ingredients  = product.get("ingredients", []) or []

    # ── Normalise ingredient names ────────────────────────────────────────────
    ingredient_names = []
    for ing in raw_ingredients:
        if isinstance(ing, dict):
            name = ing.get("name") or ing.get("text") or ""
        else:
            name = str(ing)

        name = name.lower().strip()
        name = TRANSLATION_MAP.get(name, name)
        name = E_NUMBER_MAP.get(name, name)
        ingredient_names.append(name)

    ingredient_text = " ".join(ingredient_names)

    # ── Nutrient getter ───────────────────────────────────────────────────────
    def get_nutrient(key: str, fallback: float = 0.0) -> float:
        for candidate in [key, key.replace("_100g", ""), f"{key}_100g"]:
            val = nutrients.get(candidate)
            if val is not None:
                try:
                    return float(val)
                except Exception:
                    pass
        return fallback

    # ── Core nutrients ────────────────────────────────────────────────────────
    energy    = get_nutrient("energy-kcal_100g") or get_nutrient("energy_100g") or 0.0
    sugars    = get_nutrient("sugars_100g",         0.0)
    fat       = get_nutrient("fat_100g",            0.0)
    saturated = get_nutrient("saturated-fat_100g",  0.0)
    sodium    = get_nutrient("sodium_100g",         0.0)
    fiber     = get_nutrient("fiber_100g",          0.0)
    proteins  = get_nutrient("proteins_100g",       0.0)
    carbs     = get_nutrient("carbohydrates_100g",  0.0)
    salt      = get_nutrient("salt_100g", sodium * 2.5)

    # ── Basic ingredient counts ───────────────────────────────────────────────
    ingredient_count = len(ingredient_names)
    additive_count   = len(E_NUMBER_PATTERN.findall(ingredient_text))

    # ── Additive / processing flags ───────────────────────────────────────────
    has_artificial_sweetener = int(any(sw in ingredient_text for sw in ARTIFICIAL_SWEETENERS))
    has_preservatives        = int(any(p  in ingredient_text for p  in PRESERVATIVES))
    has_harmful_additives    = int(any(h  in ingredient_text for h  in HARMFUL_ADDITIVES))

    processed_score = min(
        10.0,
        (ingredient_count * 0.3) + (additive_count * 1.5) + (has_harmful_additives * 2.0)
    )

    # ── Ratios ────────────────────────────────────────────────────────────────
    sugar_to_carb_ratio  = (sugars    / carbs) if carbs > 0 else 0.0
    sat_fat_to_fat_ratio = (saturated / fat)   if fat   > 0 else 0.0

    # ── Calorie bucket ────────────────────────────────────────────────────────
    if energy < 150:
        calorie_bucket = 0
    elif energy < 350:
        calorie_bucket = 1
    else:
        calorie_bucket = 2

    # ── Ordinal health levels ─────────────────────────────────────────────────
    sugar_level  = 0 if sugars < 5  else (1 if sugars < 15  else 2)
    salt_level   = 0 if salt   < 0.3 else (1 if salt   < 1.5 else 2)
    fiber_quality = 2 if fiber > 5   else (1 if fiber > 2    else 0)

    # ── NEW: Indian harmful ingredients ──────────────────────────────────────
    # Counts how many Indian-specific harmful ingredients are present.
    # Even one (e.g. maida as first ingredient) is a strong negative signal.
    indian_harmful_count = sum(
        1 for h in INDIAN_HARMFUL if h in ingredient_text
    )
    has_maida      = int("maida" in ingredient_text or "refined wheat flour" in ingredient_text)
    has_vanaspati  = int("vanaspati" in ingredient_text or "dalda" in ingredient_text
                         or "hydrogenated vegetable oil" in ingredient_text)
    has_palm_olein = int("palm olein" in ingredient_text or "palm kernel" in ingredient_text)

    # ── NEW: NOVA ultra-processing score (0–4 proxy) ──────────────────────────
    # Count distinct NOVA4 marker categories present; ≥2 = likely ultra-processed.
    nova4_hits = sum(1 for m in NOVA4_MARKERS if m in ingredient_text)
    nova_score = min(4, nova4_hits // 2)   # 0 = unprocessed, 4 = ultra-processed

    # ── NEW: Harmful E-number count (distinct dangerous codes) ───────────────
    harmful_e_count = len(set(HARMFUL_E_PATTERN.findall(ingredient_text)))

    # ── NEW: Healthy ingredient flags ─────────────────────────────────────────
    has_healthy_fat  = int(any(f in ingredient_text for f in HEALTHY_FATS))
    has_whole_grain  = int(any(g in ingredient_text for g in WHOLE_GRAINS))
    natural_food_count = sum(1 for n in NATURAL_FOODS if n in ingredient_text)

    # ── NEW: Protein-to-calorie ratio ─────────────────────────────────────────
    # Higher = better quality calories.  Clip at 1.0 to avoid outliers.
    protein_per_kcal = round(min((proteins * 4 / energy) if energy > 0 else 0.0, 1.0), 4)

    # ── NEW: Allergen count ───────────────────────────────────────────────────
    allergen_count = sum(1 for a in ALLERGENS if a in ingredient_text)

    # ── NEW: Free-sugar flag ──────────────────────────────────────────────────
    # 1 if any free/added sugar keyword appears in the FIRST THIRD of the
    # ingredient list (ingredient lists are by descending weight → sugar near
    # the top means it's a major ingredient, not just a trace).
    top_third      = ingredient_names[: max(1, ingredient_count // 3)]
    top_third_text = " ".join(top_third)
    free_sugar_flag = int(any(kw in top_third_text for kw in FREE_SUGAR_KEYWORDS))

    # ── Assemble feature dict ─────────────────────────────────────────────────
    features = {
        # ── Core nutrients ──
        "energy_100g":          energy,
        "sugars_100g":          sugars,
        "fat_100g":             fat,
        "saturated_fat_100g":   saturated,
        "sodium_100g":          sodium,
        "salt_100g":            salt,
        "fiber_100g":           fiber,
        "proteins_100g":        proteins,
        "carbohydrates_100g":   carbs,

        # ── Ingredient / additive counts ──
        "ingredient_count":         ingredient_count,
        "additive_count":           additive_count,
        "has_artificial_sweetener": has_artificial_sweetener,
        "has_preservatives":        has_preservatives,
        "has_harmful_additives":    has_harmful_additives,
        "processed_score":          processed_score,

        # ── Ratios / buckets ──
        "sugar_to_carb_ratio":  round(sugar_to_carb_ratio,  4),
        "sat_fat_to_fat_ratio": round(sat_fat_to_fat_ratio, 4),
        "calorie_bucket":       calorie_bucket,
        "sugar_level":          sugar_level,
        "salt_level":           salt_level,
        "fiber_quality":        fiber_quality,

        # ── NEW: Indian-specific ──
        "indian_harmful_count": indian_harmful_count,
        "has_maida":            has_maida,
        "has_vanaspati":        has_vanaspati,
        "has_palm_olein":       has_palm_olein,

        # ── NEW: NOVA / ultra-processing ──
        "nova_score":           nova_score,
        "harmful_e_count":      harmful_e_count,

        # ── NEW: Healthy signals ──
        "has_healthy_fat":      has_healthy_fat,
        "has_whole_grain":      has_whole_grain,
        "natural_food_count":   natural_food_count,

        # ── NEW: Quality ratios ──
        "protein_per_kcal":     protein_per_kcal,
        "allergen_count":       allergen_count,
        "free_sugar_flag":      free_sugar_flag,
    }

    return features


# ─── Feature column order (determines numpy vector shape) ────────────────────
# ⚠️  APPEND-ONLY — never reorder or remove existing columns or saved models
#     will predict garbage. New columns are always added at the end.
FEATURE_COLUMNS = [
    # v1 — original 21 features
    "energy_100g",
    "sugars_100g",
    "fat_100g",
    "saturated_fat_100g",
    "sodium_100g",
    "salt_100g",
    "fiber_100g",
    "proteins_100g",
    "carbohydrates_100g",
    "ingredient_count",
    "additive_count",
    "has_artificial_sweetener",
    "has_preservatives",
    "has_harmful_additives",
    "processed_score",
    "sugar_to_carb_ratio",
    "sat_fat_to_fat_ratio",
    "calorie_bucket",
    "sugar_level",
    "salt_level",
    "fiber_quality",

    # v2 — 12 new features (appended; defaults to 0.0 for old saved models)
    "indian_harmful_count",
    "has_maida",
    "has_vanaspati",
    "has_palm_olein",
    "nova_score",
    "harmful_e_count",
    "has_healthy_fat",
    "has_whole_grain",
    "natural_food_count",
    "protein_per_kcal",
    "allergen_count",
    "free_sugar_flag",
]


def features_to_vector(feature_dict: dict) -> np.ndarray:
    """Convert feature dict → ordered numpy array matching FEATURE_COLUMNS."""
    return np.array(
        [feature_dict.get(col, 0.0) for col in FEATURE_COLUMNS],
        dtype=np.float32,
    )
