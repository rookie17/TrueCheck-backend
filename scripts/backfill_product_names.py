# scripts/backfill_product_names.py

from dotenv import load_dotenv
load_dotenv()

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from firestore import db
from utils.name_utils import clean_product_name


def backfill():
    docs = list(db.collection("products").stream())
    print(f"Found {len(docs)} products\n")

    updated = 0
    skipped = 0

    for doc in docs:
        data = doc.to_dict()
        original = data.get("product_name", "")
        cleaned = clean_product_name(original)

        if cleaned == original:
            skipped += 1
            continue

        print(f"  [{doc.id}]")
        print(f"    before: {original}")
        print(f"    after:  {cleaned}")

        db.collection("products").document(doc.id).update({"product_name": cleaned})
        updated += 1

    print(f"\nDone — {updated} updated, {skipped} unchanged")


if __name__ == "__main__":
    backfill()