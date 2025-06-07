from firestore import (
    db,
    save_product_to_db,
    save_product_rating_to_db,
    save_percent_estimate_to_db,
)
from services.enrichment import enrich_ingredients
from utils.openai_client import get_product_rating_from_gemini


def prompt_for_list(prompt_text, allow_empty=False):
    print(prompt_text)
    items = []
    while True:
        item = input("→ Enter value (or leave blank to stop): ").strip()        
        if not item:
            break
        items.append(item)
    return items


def prompt_for_dict(prompt_text):
    print(prompt_text)
    result = {}
    while True:
        key = input("→ Key (or blank to stop): ").strip()
        if not key:
            break
        key = key+"_100g"
        value = input(f"→ Value for '{key}': ").strip()
        result[key] = value
    return result


def handle_percent_estimates(ingredient_count):
    print("📊 Enter percent estimates (same order as ingredients).")
    print("📝 Leave blank for unknown values.\n")
    estimates = []
    for i in range(ingredient_count):
        value = input(f"→ Percent for ingredient {i+1}: ").strip()
        estimates.append(value if value else "not avail")
    return estimates


def main():
    products_ref = db.collection("products")
    docs = products_ref.stream()

    for doc in docs:
        data = doc.to_dict()
        barcode = doc.id
        ingredients = data.get("ingredients", [])

        if not ingredients:
            confirmation = input(f"Do you want to fix: {barcode}?\nY or N: ")
            if confirmation.strip().lower() in ('n','no') :
                db.collection("products").document(barcode).delete()
                continue
                
            print(f"\n📦 Fixing product: {barcode}")

            # Ask for product name if missing
            product_name = data.get("product_name", "").strip()
            if not product_name:
                product_name = input("📝 Enter product name: ").strip()

            # Collect missing inputs
            ingredient_names = prompt_for_list("🥣 Enter ingredient names (one per line):")
            percent_estimate = handle_percent_estimates(len(ingredient_names))
            nutrients = prompt_for_dict("⚗️ Enter nutrients_per_100g (key-value pairs):")

            # Save minimal product data
            save_product_to_db(barcode, product_name, ingredient_names, nutrients)
            save_percent_estimate_to_db(barcode, percent_estimate)

            # Enrich and rate
            enriched = enrich_ingredients(ingredient_names)
            product_rating = get_product_rating_from_gemini(enriched, percent_estimate)
            save_product_rating_to_db(barcode, product_rating)

            print(f"✅ Fixed product: {barcode}\n")

if __name__ == "__main__":
    main()

