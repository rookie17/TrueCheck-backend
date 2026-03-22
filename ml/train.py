"""
TrueCheck — Training Pipeline
================================
Trains a GradientBoosting / RandomForest ensemble on:
  1. Bootstrap dataset (always included as baseline)
  2. Real products stored in Firebase (grows over time)

Usage:
    python -m ml.train                        # full retrain
    python -m ml.train --firebase-only        # only real data (needs 50+)
    python -m ml.train --min-samples 100      # wait for 100 real samples
"""

import argparse
import json
import os
import time
import numpy as np
import joblib

from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.metrics import mean_absolute_error, r2_score

from ml.feature_engineering import extract_features, FEATURE_COLUMNS, features_to_vector
from ml.bootstrap_data import generate_bootstrap_dataset, save_bootstrap_dataset

MODEL_PATH       = "model/truecheck_model.joblib"
METADATA_PATH    = "model/model_metadata.json"
BOOTSTRAP_PATH   = "model/bootstrap_dataset.json"
MIN_SAMPLES      = 30   # minimum total samples before training


# ─── Data Loading ─────────────────────────────────────────────────────────────

def load_bootstrap_data() -> list:
    if not os.path.exists(BOOTSTRAP_PATH):
        print("📦 Generating bootstrap dataset...")
        save_bootstrap_dataset(BOOTSTRAP_PATH)
    with open(BOOTSTRAP_PATH) as f:
        return json.load(f)


def load_firebase_data() -> list:
    """
    Pull real products from Firebase that have an overall_score saved.
    Returns list of product dicts.
    """
    try:
        from firestore import db
        docs = db.collection("products").stream()
        products = []
        for doc in docs:
            data = doc.to_dict()
            rating = data.get("product_rating", {})

            # Support both numeric score and dict with 'overall_score' key
            if isinstance(rating, (int, float)):
                overall_score = float(rating)
            elif isinstance(rating, dict):
                overall_score = rating.get("overall_score") or rating.get("score")
                if overall_score is None:
                    continue
                overall_score = float(overall_score)
            else:
                continue

            products.append({
                "barcode":            doc.id,
                "product_name":       data.get("product_name", ""),
                "ingredients":        data.get("ingredients", []),
                "nutrients_per_100g": data.get("nutrients_per_100g", {}),
                "overall_score":      overall_score,
            })
        print(f"🔥 Loaded {len(products)} real products from Firebase")
        return products
    except Exception as e:
        print(f"⚠️  Firebase unavailable ({e}). Using bootstrap data only.")
        return []


# ─── Feature Matrix Builder ───────────────────────────────────────────────────

def build_dataset(products: list):
    """Convert list of product dicts → (X, y) numpy arrays."""
    X, y = [], []
    skipped = 0
    for p in products:
        try:
            feat = extract_features(p)
            vec  = features_to_vector(feat)
            score = float(p["overall_score"])
            if not (0.0 <= score <= 10.0):
                skipped += 1
                continue
            X.append(vec)
            y.append(score)
        except Exception:
            skipped += 1
    if skipped:
        print(f"   ⚠️  Skipped {skipped} products (bad data)")
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)


# ─── Model Definition ─────────────────────────────────────────────────────────

def build_model():
    """
    Gradient Boosting Regressor wrapped in a sklearn Pipeline.
    GBR chosen over RandomForest for better accuracy on tabular data.
    """
    return Pipeline([
        ("scaler", StandardScaler()),
        ("gbr", GradientBoostingRegressor(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            min_samples_split=5,
            min_samples_leaf=3,
            subsample=0.8,
            random_state=42,
        ))
    ])


# ─── Training Entry Point ─────────────────────────────────────────────────────

def train(firebase_only: bool = False, min_samples: int = MIN_SAMPLES):
    os.makedirs("model", exist_ok=True)

    # ── Load data ────────────────────────────────────────────────────────────
    firebase_products = load_firebase_data()
    bootstrap_products = [] if firebase_only else load_bootstrap_data()

    all_products = bootstrap_products + firebase_products
    print(f"\n📊 Total training samples: {len(all_products)}"
          f"  (bootstrap={len(bootstrap_products)}, firebase={len(firebase_products)})")

    if len(all_products) < min_samples:
        print(f"❌ Not enough samples. Need {min_samples}, have {len(all_products)}. Aborting.")
        return None

    # ── Build feature matrix ─────────────────────────────────────────────────
    X, y = build_dataset(all_products)
    print(f"   Feature matrix shape: {X.shape}")

    # ── Train / test split ───────────────────────────────────────────────────
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.15, random_state=42
    )

    # ── Train ────────────────────────────────────────────────────────────────
    print("\n🏋️  Training GradientBoosting model...")
    model = build_model()
    t0 = time.time()
    model.fit(X_train, y_train)
    elapsed = time.time() - t0

    # ── Evaluate ─────────────────────────────────────────────────────────────
    y_pred   = model.predict(X_test)
    mae      = mean_absolute_error(y_test, y_pred)
    r2       = r2_score(y_test, y_pred)
    cv_mae   = -cross_val_score(model, X, y, cv=5, scoring="neg_mean_absolute_error").mean()

    print(f"\n📈 Evaluation on held-out test set:")
    print(f"   MAE  : {mae:.3f}")
    print(f"   R²   : {r2:.3f}")
    print(f"   CV-MAE (5-fold): {cv_mae:.3f}")
    print(f"   Training time  : {elapsed:.1f}s")

    # ── Feature importance ────────────────────────────────────────────────────
    gbr = model.named_steps["gbr"]
    importances = sorted(
        zip(FEATURE_COLUMNS, gbr.feature_importances_),
        key=lambda x: x[1], reverse=True
    )
    print("\n🔍 Top 5 most important features:")
    for name, imp in importances[:5]:
        print(f"   {name:<30} {imp:.4f}")

    # ── Save model ────────────────────────────────────────────────────────────
    joblib.dump(model, MODEL_PATH)
    print(f"\n💾 Model saved → {MODEL_PATH}")

    # ── Save metadata ─────────────────────────────────────────────────────────
    metadata = {
        "trained_at":         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_samples":      int(len(X)),
        "bootstrap_samples":  len(bootstrap_products),
        "firebase_samples":   len(firebase_products),
        "mae":                round(float(mae), 4),
        "r2":                 round(float(r2), 4),
        "cv_mae":             round(float(cv_mae), 4),
        "feature_columns":    FEATURE_COLUMNS,
        "feature_importances": {k: round(float(v), 4) for k, v in importances},
    }
    with open(METADATA_PATH, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"📋 Metadata saved → {METADATA_PATH}\n")

    return model


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TrueCheck model trainer")
    parser.add_argument("--firebase-only", action="store_true",
                        help="Skip bootstrap data, use only Firebase products")
    parser.add_argument("--min-samples", type=int, default=MIN_SAMPLES,
                        help="Minimum samples required before training")
    args = parser.parse_args()
    train(firebase_only=args.firebase_only, min_samples=args.min_samples)
