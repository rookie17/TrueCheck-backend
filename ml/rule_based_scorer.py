"""
Rule-Based Scorer — TrueCheck Bootstrap
----------------------------------------
Generates deterministic 0–10 health scores from product features.
Used ONLY to create initial training data before real ratings exist.
Once you have 100+ real products, this becomes irrelevant.
"""

from ml.feature_engineering import extract_features


def rule_based_score(product: dict) -> float:
    """
    Compute a deterministic health score (0–10) from product data.
    Higher = healthier.

    Scoring logic (evidence-based nutritional heuristics):
      + fiber, protein → positive
      – sugar, saturated fat, salt, additives, harmful additives → negative
    """
    f = extract_features(product)

    score = 5.0  # neutral baseline

    # ── Positive contributions ────────────────────────────────────────────────
    score += min(f["fiber_100g"] * 0.4,   2.0)   # fiber is good
    score += min(f["proteins_100g"] * 0.1, 1.5)  # protein is good

    # ── Negative contributions ────────────────────────────────────────────────
    score -= min(f["sugars_100g"] * 0.12,  2.5)  # high sugar → bad
    score -= min(f["saturated_fat_100g"] * 0.15, 2.0)
    score -= min(f["salt_100g"] * 0.8,     1.5)
    score -= min(f["additive_count"] * 0.4, 2.0)
    score -= f["has_artificial_sweetener"] * 0.5
    score -= f["has_preservatives"] * 0.5
    score -= f["has_harmful_additives"] * 1.0

    # ── Ingredient complexity penalty ─────────────────────────────────────────
    if f["ingredient_count"] > 20:
        score -= 1.0
    elif f["ingredient_count"] > 10:
        score -= 0.5

    # ── Calorie density ───────────────────────────────────────────────────────
    if f["calorie_bucket"] == 2:
        score -= 0.5
    elif f["calorie_bucket"] == 0:
        score += 0.3

    return round(max(0.0, min(10.0, score)), 2)
