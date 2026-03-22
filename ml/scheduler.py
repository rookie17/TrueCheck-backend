"""
TrueCheck — Self-Learning Scheduler
======================================
Monitors Firebase for new products and triggers model retraining
when enough new data has accumulated.

Run as a background process:
    python -m ml.scheduler

Or integrate with cron:
    0 3 * * * cd /your/project && python -m ml.scheduler --once
"""
from dotenv import load_dotenv
load_dotenv()

import argparse
import json
import os
import time

METADATA_PATH     = "model/model_metadata.json"
RETRAIN_THRESHOLD = 50    # retrain after this many NEW Firebase samples
CHECK_INTERVAL    = 3600  # check every 1 hour (seconds)


def get_last_firebase_count() -> int:
    """Read firebase_samples count from last training metadata."""
    if not os.path.exists(METADATA_PATH):
        return 0
    with open(METADATA_PATH) as f:
        meta = json.load(f)
    return meta.get("firebase_samples", 0)


def get_current_firebase_count() -> int:
    """Count products in Firebase that have a rating (eligible for training)."""
    try:
        from firestore import db
        docs  = db.collection("products").stream()
        count = 0
        for doc in docs:
            data   = doc.to_dict()
            rating = data.get("product_rating")
            if rating is not None:
                count += 1
        return count
    except Exception as e:
        print(f"⚠️  Firebase error: {e}")
        return 0


def should_retrain() -> tuple[bool, int, int]:
    """
    Check if retraining is needed.
    Returns: (should_retrain, current_count, last_count)
    """
    last    = get_last_firebase_count()
    current = get_current_firebase_count()
    delta   = current - last
    return delta >= RETRAIN_THRESHOLD, current, last


def run_retrain():
    """Trigger the training pipeline."""
    from ml.train import train
    print(f"\n🔄 Retraining triggered at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    train()


def run_scheduler(once: bool = False, threshold: int = RETRAIN_THRESHOLD):
    global RETRAIN_THRESHOLD
    RETRAIN_THRESHOLD = threshold

    print("🤖 TrueCheck Self-Learning Scheduler started")
    print(f"   Retrain threshold : {RETRAIN_THRESHOLD} new products")
    print(f"   Check interval    : {CHECK_INTERVAL}s")

    while True:
        needs_retrain, current, last = should_retrain()
        print(f"\n[{time.strftime('%H:%M:%S')}] Firebase products with rating: {current}"
              f"  (last train: {last}, delta: {current - last})")

        if needs_retrain:
            run_retrain()
        else:
            remaining = RETRAIN_THRESHOLD - (current - last)
            print(f"   ⏳ Need {remaining} more products before retraining.")

        if once:
            break

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TrueCheck retraining scheduler")
    parser.add_argument("--once",      action="store_true",
                        help="Run check once and exit")
    parser.add_argument("--threshold", type=int, default=RETRAIN_THRESHOLD,
                        help="New-product threshold to trigger retraining")
    args = parser.parse_args()
    run_scheduler(once=args.once, threshold=args.threshold)
