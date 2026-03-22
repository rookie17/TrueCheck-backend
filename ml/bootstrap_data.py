"""
Bootstrap Dataset Generator — TrueCheck
-----------------------------------------
Creates a synthetic training dataset of ~300 products using rule-based scores.
Run this ONCE to seed the model before real data accumulates.

Usage:
    python -m ml.bootstrap_data
"""

import json
import random
import os
from ml.rule_based_scorer import rule_based_score

random.seed(42)

# ─── Ingredient pools ─────────────────────────────────────────────────────────

NATURAL_INGREDIENTS = [
    "water", "wheat flour", "oats", "whole grain wheat", "rice",
    "milk", "eggs", "butter", "olive oil", "sunflower oil",
    "sugar", "salt", "yeast", "baking soda", "baking powder",
    "cocoa", "chocolate", "vanilla", "cinnamon", "honey",
    "almonds", "walnuts", "cashews", "peanuts", "sesame seeds",
    "tomatoes", "onions", "garlic", "potatoes", "carrots",
    "spinach", "broccoli", "corn", "peas", "lentils",
    "soy protein", "whey protein", "casein", "skim milk powder",
    "fruit juice concentrate", "apple puree", "banana puree",
    "oat fiber", "wheat bran", "inulin", "psyllium husk",
]

ADDITIVE_INGREDIENTS = [
    "E211", "E202", "E102", "E110", "E129", "E133",
    "sodium benzoate", "potassium sorbate", "carrageenan",
    "high fructose corn syrup", "aspartame", "sucralose",
    "BHA", "BHT", "TBHQ", "monosodium glutamate",
    "titanium dioxide", "partially hydrogenated soybean oil",
    "red 40", "yellow 5", "artificial flavor", "artificial color",
]


def _random_nutrients(profile: str) -> dict:
    """Generate realistic nutrient values based on product health profile."""
    if profile == "healthy":
        return {
            "energy_100g":          random.uniform(80, 250),
            "sugars_100g":          random.uniform(0, 8),
            "fat_100g":             random.uniform(1, 10),
            "saturated-fat_100g":   random.uniform(0, 3),
            "sodium_100g":          random.uniform(0, 0.3),
            "salt_100g":            random.uniform(0, 0.8),
            "fiber_100g":           random.uniform(3, 10),
            "proteins_100g":        random.uniform(5, 20),
            "carbohydrates_100g":   random.uniform(10, 40),
        }
    elif profile == "moderate":
        return {
            "energy_100g":          random.uniform(200, 400),
            "sugars_100g":          random.uniform(5, 20),
            "fat_100g":             random.uniform(5, 20),
            "saturated-fat_100g":   random.uniform(2, 8),
            "sodium_100g":          random.uniform(0.2, 0.8),
            "salt_100g":            random.uniform(0.5, 2.0),
            "fiber_100g":           random.uniform(1, 5),
            "proteins_100g":        random.uniform(3, 12),
            "carbohydrates_100g":   random.uniform(30, 60),
        }
    else:  # unhealthy
        return {
            "energy_100g":          random.uniform(350, 600),
            "sugars_100g":          random.uniform(20, 50),
            "fat_100g":             random.uniform(15, 35),
            "saturated-fat_100g":   random.uniform(6, 18),
            "sodium_100g":          random.uniform(0.6, 2.0),
            "salt_100g":            random.uniform(1.5, 5.0),
            "fiber_100g":           random.uniform(0, 2),
            "proteins_100g":        random.uniform(1, 6),
            "carbohydrates_100g":   random.uniform(50, 80),
        }


def _random_ingredients(profile: str) -> list:
    """Pick ingredients biased toward health profile."""
    if profile == "healthy":
        n_natural = random.randint(3, 8)
        n_additive = random.randint(0, 1)
    elif profile == "moderate":
        n_natural = random.randint(5, 12)
        n_additive = random.randint(1, 4)
    else:
        n_natural = random.randint(6, 15)
        n_additive = random.randint(3, 8)

    ingredients = (
        random.sample(NATURAL_INGREDIENTS, min(n_natural, len(NATURAL_INGREDIENTS)))
        + random.sample(ADDITIVE_INGREDIENTS, min(n_additive, len(ADDITIVE_INGREDIENTS)))
    )
    random.shuffle(ingredients)
    return ingredients


def generate_bootstrap_dataset(n_samples: int = 300) -> list:
    """Generate n_samples synthetic products with rule-based scores."""
    dataset = []
    profiles = ["healthy", "moderate", "unhealthy"]
    weights  = [0.35, 0.40, 0.25]

    for i in range(n_samples):
        profile = random.choices(profiles, weights=weights)[0]
        product = {
            "barcode":           f"BOOTSTRAP_{i:04d}",
            "product_name":      f"Synthetic Product {i:04d} ({profile})",
            "ingredients":       _random_ingredients(profile),
            "nutrients_per_100g": _random_nutrients(profile),
        }
        score = rule_based_score(product)
        product["overall_score"] = score
        dataset.append(product)

    return dataset


def save_bootstrap_dataset(path: str = "model/bootstrap_dataset.json"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dataset = generate_bootstrap_dataset(300)
    with open(path, "w") as f:
        json.dump(dataset, f, indent=2)
    print(f"✅ Saved {len(dataset)} bootstrap products → {path}")
    scores = [d["overall_score"] for d in dataset]
    print(f"   Score range: {min(scores):.2f} – {max(scores):.2f}  |  mean: {sum(scores)/len(scores):.2f}")
    return path


if __name__ == "__main__":
    save_bootstrap_dataset()
