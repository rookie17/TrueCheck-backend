# main.py

from dotenv import load_dotenv
load_dotenv()

import logging
import re
from flask import Flask, jsonify, request
from flask_cors import CORS

from firestore import (
    get_product_from_db, save_product_to_db,
    get_ingredient_profile_from_db, save_ingredient_to_db,
    save_percent_estimate_to_db, save_product_rating_to_db,
    get_product_rating_from_db,
    get_recent_products, save_image_url_to_db
)
from utils.name_utils import clean_product_name
from utils.llm_client import get_ingredient_profile_from_llm, get_product_rating_from_llm
from services.enrichment import enrich_ingredients
from services.openfoodfacts_api import get_product_from_openfoodfacts
from services.nutrition_fetcher import fetch_nutrition_from_barcode
from services.percent_estimate import get_percent_estimates
from services.upcitemdb import get_product_name_from_barcode
from services.barcode_resolver import resolve_product_name
from services.scrapers.bigbasket import get_product_by_name as bb_get_product_by_name, get_product_image_url as bb_get_image_url
from services.scrapers.blinkit import scrape_blinkit
from utils.ingredient_utils import extract_ingredient_text
from services.ocr_processor import process_ocr_inputs

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_ingredients_from_raw(raw: str) -> list[str]:
    cleaned = re.sub(r"\(\d+\.?\d*%\)", "", raw)
    parts = [p.strip() for p in cleaned.split(",")]
    return [p for p in parts if len(p) > 1 and not p.replace(".", "").isdigit()]


def _clean_name_for_search(name: str) -> str:
    name = re.sub(r",?\s*\d+\.?\d*\s*(g|kg|ml|l|oz|lb)\b", "", name, flags=re.IGNORECASE)
    name = name.replace("/", " ")
    name = re.sub(r"[,\-]+$", "", name).strip()
    return name


# ── Main route ────────────────────────────────────────────────────────────────

@app.route("/get-complete-product-info", methods=["GET"])
def get_complete_product_info():
    barcode = request.args.get("barcode")
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400

    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("REQUEST  barcode=%s", barcode)

    data_sources = {
        "product":     None,
        "ingredients": None,
        "nutrition":   None,
        "name":        None,
        "rating":      None,
    }

    # ── 1. Firestore cache ────────────────────────────────────────────────────
    product_data = get_product_from_db(barcode)

    if product_data:
        logger.info("CACHE    HIT — product found in Firestore")
        data_sources["product"] = "firestore_cache"

        product_name       = product_data.get("product_name", "Unknown")
        cached_ingredients = product_data.get("ingredients", [])
        nutrition_data     = product_data.get("nutrients_per_100g", {})
        off_product_data   = None

        logger.info("CACHE    name='%s'  ingredients=%d  nutrients=%d",
                    product_name, len(cached_ingredients), len(nutrition_data))

        if nutrition_data:
            data_sources["nutrition"] = "firestore_cache"
        if cached_ingredients:
            data_sources["ingredients"] = "firestore_cache"
        data_sources["name"] = "firestore_cache"
        image_url = product_data.get("image_url")
        if not image_url:
            logger.info("IMAGE    not cached — fetching from BigBasket...")
            image_url = bb_get_image_url(product_name)
            save_image_url_to_db(barcode, image_url)
        else:
            logger.info("IMAGE    loaded from cache")

    else:
        logger.info("CACHE    MISS — fetching from external sources")

        # ── 2. OpenFoodFacts ──────────────────────────────────────────────────
        logger.info("SOURCE   trying OpenFoodFacts...")
        off_product = get_product_from_openfoodfacts(barcode)

        product_name         = None
        raw_ingredient_names = []
        nutrition_data       = {}
        off_product_data     = None

        if off_product:
            product_name = off_product.get("product_name", "Unknown")
            raw_ingredient_names = [
                extract_ingredient_text(i)
                for i in off_product.get("ingredients", [])
                if extract_ingredient_text(i)
            ]
            nutriments       = off_product.get("nutriments", {})
            nutrition_data   = {k: v for k, v in nutriments.items() if k.endswith("_100g")}
            off_product_data = off_product

            logger.info("OFf      name='%s'  ingredients=%d  nutrients=%d",
                        product_name, len(raw_ingredient_names), len(nutrition_data))

            data_sources["name"] = "openfoodfacts"
            if nutrition_data:
                data_sources["nutrition"] = "openfoodfacts"
            if raw_ingredient_names:
                data_sources["ingredients"] = "openfoodfacts"
        else:
            logger.info("OFf      no result for barcode %s", barcode)

        # ── 3. Name resolution + BB fallback ─────────────────────────────────
        if not off_product or not raw_ingredient_names:
            logger.info("FALLBACK ingredients missing — starting name resolution")

            if not product_name or product_name == "Unknown":
                logger.info("NAME     trying DuckDuckGo / Serper...")
                product_name = resolve_product_name(barcode)
                if product_name:
                    logger.info("NAME     resolved='%s'  source=barcode_resolver", product_name)
                    data_sources["name"] = "barcode_resolver (DDG/Serper)"
                else:
                    logger.info("NAME     barcode_resolver returned nothing")

            if not product_name or product_name == "Unknown":
                logger.info("NAME     trying UPCitemdb...")
                product_name = get_product_name_from_barcode(barcode)
                if product_name:
                    logger.info("NAME     resolved='%s'  source=upcitemdb", product_name)
                    data_sources["name"] = "upcitemdb"
                else:
                    logger.info("NAME     upcitemdb returned nothing")

            if product_name:
                bb_search_name = _clean_name_for_search(product_name)
                logger.info("BB       searching BigBasket for '%s'...", bb_search_name)
                bb_data = bb_get_product_by_name(bb_search_name)

                if bb_data and bb_data.get("ingredients_raw"):
                    raw_ingredient_names = _parse_ingredients_from_raw(bb_data["ingredients_raw"])
                    logger.info("BB       ingredients=%d", len(raw_ingredient_names))
                    data_sources["ingredients"] = "bigbasket"

                    if not nutrition_data and bb_data.get("nutrition"):
                        nutrition_data = bb_data["nutrition"]
                        logger.info("BB       nutrition=%d fields", len(nutrition_data))
                        data_sources["nutrition"] = "bigbasket"

                else:
                    logger.info("BB       no ingredients returned for '%s' — trying Blinkit", bb_search_name)
                    blinkit_data = scrape_blinkit(product_name)

                    if blinkit_data and blinkit_data.get("ingredients"):
                        raw_ingredient_names = blinkit_data["ingredients"]
                        logger.info("BLINKIT  ingredients=%d", len(raw_ingredient_names))
                        data_sources["ingredients"] = "blinkit"

                        if not nutrition_data and blinkit_data.get("nutrients_per_100g"):
                            nutrition_data = blinkit_data["nutrients_per_100g"]
                            logger.info("BLINKIT  nutrition=%d fields", len(nutrition_data))
                            data_sources["nutrition"] = "blinkit"
                    else:
                        logger.info("BLINKIT  no ingredients returned for '%s'", product_name)
            else:
                logger.info("FALLBACK no product name — cannot search BB")

        if not raw_ingredient_names:
            logger.warning("FAIL     no ingredients from any source for barcode %s", barcode)
            return jsonify({
                "error":        "Product not found or ingredients unavailable",
                "product_name": product_name or "Unknown",
                "data_sources": data_sources,
            }), 404

        product_name = clean_product_name(product_name or "Unknown")
        image_url = bb_get_image_url(product_name)
        logger.info("IMAGE    fetched → %s", image_url)
        save_product_to_db(barcode, product_name, raw_ingredient_names, nutrition_data, image_url=image_url)
        logger.info("DB       product saved to Firestore")
        cached_ingredients = [{"name": n, "profile": None} for n in raw_ingredient_names]

    # ── 4. Ingredient profiles ────────────────────────────────────────────────
    logger.info("ENRICH   fetching profiles for %d ingredients...", len(cached_ingredients))
    final_ingredient_list = []
    profile_sources = {"firestore": 0, "llm": 0, "passthrough": 0}

    for item in cached_ingredients:
        if isinstance(item, dict) and item.get("profile"):
            final_ingredient_list.append(item)
            profile_sources["passthrough"] += 1
            continue

        name_str = item.get("name") if isinstance(item, dict) else str(item)
        name_str = str(name_str).strip().lower()
        if not name_str:
            continue

        profile_doc = get_ingredient_profile_from_db(name_str)
        if profile_doc:
            profile_sources["firestore"] += 1
        else:
            profile_doc = get_ingredient_profile_from_llm(name_str)
            if profile_doc and "error" not in profile_doc:
                save_ingredient_to_db(name_str, name_str, profile_doc)
            profile_sources["llm"] += 1

        final_ingredient_list.append({"name": name_str, "profile": profile_doc})

    logger.info("ENRICH   done — firestore=%d  llm=%d  passthrough=%d",
                profile_sources["firestore"], profile_sources["llm"], profile_sources["passthrough"])

    # ── 5. Percent estimates ──────────────────────────────────────────────────
    ingredient_names_only = [
        i.get("name", "") if isinstance(i, dict) else i
        for i in cached_ingredients
    ]
    percent_estimates = get_percent_estimates(barcode, ingredient_names_only, product_data=off_product_data)
    available = sum(1 for p in percent_estimates if p != "Not Available")
    logger.info("PERCENT  %d/%d values available", available, len(percent_estimates))

    # ── 6. Rating ─────────────────────────────────────────────────────────────
    product_rating = get_product_rating_from_db(barcode)
    if product_rating:
        logger.info("RATING   loaded from Firestore cache")
        data_sources["rating"] = "firestore_cache"
    else:
        logger.info("RATING   generating via LLM (Groq)...")
        product_rating = get_product_rating_from_llm(final_ingredient_list, percent_estimates)
        save_product_rating_to_db(barcode, product_rating)
        score = product_rating.get("product_score", "?")
        logger.info("RATING   score=%s  saved to Firestore", score)
        data_sources["rating"] = "llm (groq)"

    logger.info("DONE     barcode=%s  name='%s'", barcode, product_name)
    logger.info("SOURCES  %s", data_sources)
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    return jsonify({
        "product_name":        product_name,
        "ingredients_profile": final_ingredient_list,
        "nutrients":           nutrition_data,
        "percent_estimate":    percent_estimates,
        "overall_rating":      product_rating,
        "data_sources":        data_sources,
        "image_url":           image_url,
    })

#──── Explore Page Route ─────────────────────────────────────────────────────────────
@app.route("/get-recent-products", methods=["GET"])
def get_recent_products_route():
    try:
        limit = min(int(request.args.get("limit", 20)), 100)
    except ValueError:
        return jsonify({"error": "Invalid limit parameter"}), 400

    sort_by = request.args.get("sort", "recent")
    if sort_by not in ("recent", "most_scanned", "highly_rated"):
        return jsonify({"error": "sort must be one of: recent, most_scanned, highly_rated"}), 400

    products = get_recent_products(limit=limit, sort_by=sort_by)
    return jsonify({"products": products, "count": len(products)})


# ── OCR route ──────────────────────────────────────────────────────────────


@app.route("/scan-ocr", methods=["POST"])
def scan_ocr():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Request body must be JSON"}), 400
 
    # ── Direct barcode from mobile_scanner (preferred) ────────────────────────
    # Frontend sends 'barcode' when the user scanned it with mobile_scanner.
    # In that case skip OCR extraction for the barcode entirely.
    direct_barcode  = body.get("barcode")
    barcode_ocr     = body.get("barcode_ocr", "")
    name_ocr        = body.get("name_ocr", "")
    ingredients_ocr = body.get("ingredients_ocr", "")
 
    if not ingredients_ocr:
        return jsonify({"error": "ingredients_ocr is required"}), 400
 
    # Validate direct barcode if provided
    if direct_barcode is not None:
        direct_barcode = str(direct_barcode).strip()
        import re as _re
        if not _re.fullmatch(r"\d{8,14}", direct_barcode):
            logger.warning("OCR  direct barcode failed validation ('%s') — ignoring", direct_barcode)
            direct_barcode = None
 
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("OCR-SCAN request received  direct_barcode=%s", direct_barcode)
 
    # ── Extract from OCR blobs ────────────────────────────────────────────────
    if direct_barcode:
        # Barcode already clean — only extract name + ingredients from OCR
        logger.info("OCR      barcode provided directly — skipping barcode OCR extraction")
        extracted = process_ocr_inputs(
            barcode_ocr     = "",          # empty — won't be used for barcode
            name_ocr        = name_ocr,
            ingredients_ocr = ingredients_ocr,
            override_barcode = direct_barcode,
        )
    else:
        extracted = process_ocr_inputs(
            barcode_ocr     = barcode_ocr,
            name_ocr        = name_ocr,
            ingredients_ocr = ingredients_ocr,
        )
 
    barcode      = extracted.get("barcode")
    product_name = extracted.get("product_name") or "Unknown"
    ingredients  = extracted.get("ingredients")
    ocr_method   = extracted.get("extraction_method")
 
    logger.info(
        "OCR      method=%s  barcode=%s  name='%s'  ingredients=%d",
        ocr_method, barcode, product_name,
        len(ingredients) if ingredients else 0,
    )
 
    if not ingredients:
        logger.warning("OCR      could not extract any ingredients from provided text")
        return jsonify({
            "error":             "Could not extract ingredients from OCR text",
            "extraction_method": ocr_method,
        }), 422
 
    data_sources = {
        "product":     f"ocr ({ocr_method})",
        "ingredients": f"ocr ({ocr_method})",
        "nutrition":   None,
        "name":        f"ocr ({ocr_method})" if product_name != "Unknown" else None,
        "rating":      None,
    }
 
    # ── Cache product under barcode ───────────────────────────────────────────
    if barcode:
        product_name = clean_product_name(product_name)
        image_url = bb_get_image_url(product_name)
        logger.info("OCR      image → %s", image_url)
        save_product_to_db(barcode, product_name, ingredients, nutrition_data=None, image_url=image_url)
        logger.info("OCR      product cached in Firestore under barcode=%s", barcode)
    else:
        logger.info("OCR      no barcode — skipping Firestore product cache")
 
    # ── Ingredient profiles (Firestore → Groq) ────────────────────────────────
    logger.info("OCR-ENRICH  fetching profiles for %d ingredients...", len(ingredients))
    final_ingredient_list = []
    profile_sources = {"firestore": 0, "llm": 0}
 
    for name_str in ingredients:
        name_str = str(name_str).strip().lower()
        if not name_str:
            continue
        profile_doc = get_ingredient_profile_from_db(name_str)
        if profile_doc:
            profile_sources["firestore"] += 1
        else:
            profile_doc = get_ingredient_profile_from_llm(name_str)
            if profile_doc and "error" not in profile_doc:
                save_ingredient_to_db(name_str, name_str, profile_doc)
            profile_sources["llm"] += 1
        final_ingredient_list.append({"name": name_str, "profile": profile_doc})
 
    logger.info("OCR-ENRICH  done — firestore=%d  llm=%d",
                profile_sources["firestore"], profile_sources["llm"])
 
    # ── Percent estimates ─────────────────────────────────────────────────────
    ingredient_names_only = [
        i.get("name", "") if isinstance(i, dict) else i
        for i in final_ingredient_list
    ]
    percent_estimates = get_percent_estimates(
        barcode or "ocr_unknown", ingredient_names_only, product_data=None
    )
 
    # ── Rating (Firestore → Groq) ─────────────────────────────────────────────
    product_rating = None
    if barcode:
        product_rating = get_product_rating_from_db(barcode)
        if product_rating:
            logger.info("OCR      rating loaded from Firestore cache")
            data_sources["rating"] = "firestore_cache"
 
    if not product_rating:
        logger.info("OCR      generating rating via Groq...")
        product_rating = get_product_rating_from_llm(final_ingredient_list, percent_estimates)
        if barcode and product_rating and "error" not in product_rating:
            save_product_rating_to_db(barcode, product_rating)
            logger.info("OCR      rating saved to Firestore")
        logger.info("OCR      score=%s", product_rating.get("product_score", "?"))
        data_sources["rating"] = "llm (groq)"
 
    logger.info("OCR-SCAN done — barcode=%s  name='%s'", barcode, product_name)
    logger.info("SOURCES  %s", data_sources)
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
 
    return jsonify({
        "product_name":        product_name,
        "ingredients_profile": final_ingredient_list,
        "nutrients":           {},
        "percent_estimate":    percent_estimates,
        "overall_rating":      product_rating,
        "data_sources":        data_sources,
        "image_url":           image_url,
        "ocr_meta": {
            "extraction_method": ocr_method,
            "barcode_recovered": barcode is not None,
            "barcode_source":    "mobile_scanner" if direct_barcode else "ocr",
        },
    })

# ── Other routes ──────────────────────────────────────────────────────────────

@app.route("/test-nutrition", methods=["GET"])
def test_nutrition():
    barcode = request.args.get("barcode")
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400
    result = fetch_nutrition_from_barcode(barcode)
    if result is None:
        return jsonify({"message": "No nutrition data found or saved."}), 404
    return jsonify({"message": "Nutrition data saved successfully.", "data": result})


@app.route("/test-llm", methods=["GET"])
def test_llm():
    ingredient_name = request.args.get("ingredient_name")
    if not ingredient_name:
        return jsonify({"error": "No ingredient name provided"}), 400
    result = get_ingredient_profile_from_llm(ingredient_name)
    return jsonify({"result": result})


@app.route("/get-product-details", methods=["GET"])
def get_product_details():
    barcode = request.args.get("barcode")
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400
    product_data = get_product_from_db(barcode)
    if product_data:
        return jsonify({
            "product_name":       product_data.get("product_name", "Unknown"),
            "ingredients":        product_data.get("ingredients", []),
            "nutrients_per_100g": product_data.get("nutrients_per_100g", {}),
        })
    product = get_product_from_openfoodfacts(barcode)
    if not product:
        return jsonify({"error": "Product not found on OpenFoodFacts"}), 404
    product_name   = product.get("product_name", "Unknown")
    ingredients    = [extract_ingredient_text(i) for i in product.get("ingredients", []) if extract_ingredient_text(i)]
    nutriments     = product.get("nutriments", {})
    nutrition_data = {k: v for k, v in nutriments.items() if k.endswith("_100g")}
    save_product_to_db(barcode, product_name, ingredients, nutrition_data)
    return jsonify({"product_name": product_name, "ingredients": enrich_ingredients(ingredients), "nutrients_per_100g": nutrition_data})


@app.route("/get-ingredients", methods=["GET"])
def get_ingredients():
    barcode = request.args.get("barcode")
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400
    product_data = get_product_from_db(barcode)
    if product_data:
        return jsonify({"product_name": product_data["product_name"], "ingredients": product_data.get("ingredients", [])})
    product = get_product_from_openfoodfacts(barcode)
    if not product:
        return jsonify({"error": "Product not found on OpenFoodFacts"}), 404
    product_name = product.get("product_name", "Unknown")
    ingredients  = [extract_ingredient_text(i) for i in product.get("ingredients", []) if extract_ingredient_text(i)]
    if not ingredients:
        return jsonify({"product_name": product_name, "ingredients": [], "note": "Ingredients not available on OFf."})
    save_product_to_db(barcode, product_name, ingredients)
    return jsonify({"product_name": product_name, "ingredients": enrich_ingredients(ingredients)})


@app.route("/get-ingredient-profile", methods=["GET"])
def get_ingredient_profile():
    ingredient_name = request.args.get("ingredient_name")
    if not ingredient_name:
        return jsonify({"error": "No ingredient_name provided"}), 400
    ingredient_name = ingredient_name.lower()
    profile = get_ingredient_profile_from_db(ingredient_name)
    if profile:
        return jsonify(profile)
    profile = get_ingredient_profile_from_llm(ingredient_name)
    if profile and "error" not in profile:
        save_ingredient_to_db(ingredient_name, ingredient_name, profile)
        return jsonify(profile)
    return jsonify({"error": "Could not retrieve ingredient profile"}), 500


@app.route("/get-overall-product-rating", methods=["GET"])
def get_overall_product_rating():
    barcode = request.args.get("barcode")
    if not barcode:
        return jsonify({"error": "No barcode provided"}), 400
    product_data = get_product_from_db(barcode)
    if not product_data:
        return jsonify({"error": "Product not found in DB"}), 404
    ingredients = product_data.get("ingredients")
    if not ingredients:
        return jsonify({"error": "No ingredients found. Please enrich first."}), 400
    result = get_product_rating_from_llm(ingredients, ["not avail"] * len(ingredients))
    return jsonify(result)


if __name__ == "__main__":
    app.run()