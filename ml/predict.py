"""
TrueCheck — Prediction Pipeline
=================================
Loads the trained model and predicts a health score for a new product.
Falls back to rule-based scoring if the model file doesn't exist yet.
"""

import os
import json
import joblib
import numpy as np
from typing import Optional

from ml.feature_engineering import extract_features, FEATURE_COLUMNS, features_to_vector
from ml.rule_based_scorer   import rule_based_score

MODEL_PATH    = "model/truecheck_model.joblib"
METADATA_PATH = "model/model_metadata.json"

# ── Module-level model cache (avoid reloading on every request) ───────────────
_model       = None
_model_mtime = None


def _load_model():
    """Load model from disk, reload automatically if file has changed."""
    global _model, _model_mtime

    if not os.path.exists(MODEL_PATH):
        return None

    mtime = os.path.getmtime(MODEL_PATH)
    if _model is None or mtime != _model_mtime:
        _model       = joblib.load(MODEL_PATH)
        _model_mtime = mtime
        print(f"[OK] Model loaded from {MODEL_PATH}")

    return _model


def predict_score(product: dict) -> dict:
    """
    Predict the health score for a product.

    Args:
        product: {
            "product_name": str,
            "ingredients": list,
            "nutrients_per_100g": dict,
        }

    Returns:
        {
            "overall_score": float,       # 0–10
            "method": "ml" | "rule_based",
            "confidence": "high" | "medium" | "low",
            "features": dict,             # extracted feature snapshot
            "breakdown": dict,            # human-readable score components
        }
    """
    features    = extract_features(product)
    model       = _load_model()

    if model is not None:
        vec         = features_to_vector(features).reshape(1, -1)
        raw_score   = float(model.predict(vec)[0])
        score       = round(max(0.0, min(10.0, raw_score)), 2)
        method      = "ml"
        confidence  = _estimate_confidence(features)
    else:
        # Fallback: rule-based score until model is trained
        score       = rule_based_score(product)
        method      = "rule_based"
        confidence  = "low"

    breakdown = _build_breakdown(features, score)

    return {
        "overall_score": score,
        "method":        method,
        "confidence":    confidence,
        "features":      features,
        "breakdown":     breakdown,
    }


def _estimate_confidence(features: dict) -> str:
    """
    Estimate prediction confidence based on data completeness.
    More nutrient data available → higher confidence.
    """
    nutrient_keys = [
        "energy_100g", "sugars_100g", "fat_100g",
        "fiber_100g", "proteins_100g"
    ]
    filled = sum(1 for k in nutrient_keys if features.get(k, 0) > 0)
    if filled >= 4:
        return "high"
    elif filled >= 2:
        return "medium"
    return "low"


def _build_breakdown(features: dict, score: float) -> dict:
    """Build a human-readable explanation of the score."""
    positives, negatives = [], []

    if features.get("fiber_100g", 0) >= 3:
        positives.append(f"Good fiber content ({features['fiber_100g']:.1f}g/100g)")
    if features.get("proteins_100g", 0) >= 8:
        positives.append(f"High protein ({features['proteins_100g']:.1f}g/100g)")
    if features.get("ingredient_count", 99) <= 5:
        positives.append("Short, simple ingredient list")

    if features.get("sugars_100g", 0) >= 8:
        negatives.append(f"High sugar ({features['sugars_100g']:.1f}g/100g)")
    if features.get("saturated_fat_100g", 0) >= 5:
        negatives.append(f"High saturated fat ({features['saturated_fat_100g']:.1f}g/100g)")
    if features.get("additive_count", 0) >= 3:
        negatives.append(f"{features['additive_count']} additives/E-numbers detected")
    if features.get("has_harmful_additives"):
        negatives.append("Contains potentially harmful additives")
    if features.get("has_artificial_sweetener"):
        negatives.append("Contains artificial sweeteners")

    # Grade
    if score >= 8:
        grade = "A"
    elif score >= 6:
        grade = "B"
    elif score >= 4:
        grade = "C"
    elif score >= 2:
        grade = "D"
    else:
        grade = "F"

    return {
        "grade":     grade,
        "positives": positives,
        "negatives": negatives,
    }


def get_model_metadata() -> Optional[dict]:
    """Return model training metadata if available."""
    if os.path.exists(METADATA_PATH):
        with open(METADATA_PATH) as f:
            return json.load(f)
    return None
