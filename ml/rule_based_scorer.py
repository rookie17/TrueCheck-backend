"""
Rule-Based Scorer — TrueCheck Bootstrap
----------------------------------------
Generates balanced 0–10 health scores from product features.
Designed to spread scores across the full 0–10 range.
"""

from ml.feature_engineering import extract_features


def rule_based_score(product: dict) -> float:
    f = extract_features(product)

    score = 6.0  # start from a healthier baseline

    # ── Strong positive contributions ─────────────────────────────────────────
    score += min(f["fiber_100g"] * 0.5,    2.5)   # fiber is very important
    score += min(f["proteins_100g"] * 0.12, 1.5)  # protein matters

    # ── Negative contributions (reduced penalties) ────────────────────────────
    score -= min(f["sugars_100g"] * 0.05,   2.0)  # sugar penalty (reduced)
    score -= min(f["saturated_fat_100g"] * 0.08, 1.5)  # sat fat (reduced)
    score -= min(f["salt_100g"] * 0.5,      1.0)  # salt penalty
    score -= min(f["additive_count"] * 0.3, 1.5)  # additives

    # ── Harmful ingredient flags ──────────────────────────────────────────────
    score -= f["has_artificial_sweetener"] * 0.5
    score -= f["has_preservatives"] * 0.3
    score -= f["has_harmful_additives"] * 1.0

    # ── Ingredient complexity ─────────────────────────────────────────────────
    if f["ingredient_count"] > 20:
        score -= 1.0
    elif f["ingredient_count"] > 10:
        score -= 0.3

    # ── Calorie density ───────────────────────────────────────────────────────
    if f["calorie_bucket"] == 2:
        score -= 0.3
    elif f["calorie_bucket"] == 0:
        score += 0.5   # low calorie boost

    return round(max(0.0, min(10.0, score)), 2)
