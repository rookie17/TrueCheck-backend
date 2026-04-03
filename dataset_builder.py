from dotenv import load_dotenv
load_dotenv()
import pandas as pd # type: ignore
from firestore import db
from ml.feature_engineering import extract_features

def build_dataset():
    docs = db.collection("products").stream()

    rows = []

    for doc in docs:
        data = doc.to_dict()

        product = {
            "ingredients": data.get("ingredients", []),
            "nutrients_per_100g": data.get("nutrients_per_100g", {})
        }

        features = extract_features(product)

        # 🎯 TARGET LABEL (IMPORTANT)
        rating = data.get("product_rating", {}).get("overall_score")

        if rating is None:
            continue

        features["label"] = rating
        rows.append(features)

    df = pd.DataFrame(rows)
    df.to_csv("dataset.csv", index=False)

    print("Dataset created:", len(df))

if __name__ == "__main__":
    build_dataset()