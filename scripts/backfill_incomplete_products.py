"""
scripts/backfill_incomplete_products.py
========================================
Loops through every product in Firestore, detects what's missing,
and fills it using the same fallback chain as /get-complete-product-info.

Completeness checklist per product:
  ✓ product_name          — non-empty, not "Unknown"
  ✓ ingredients           — non-empty list
  ✓ nutrients_per_100g    — non-empty dict
  ✓ percent_estimate      — list present
  ✓ product_rating        — dict present
  ✓ image_url             — non-null string

Run:
  python scripts/backfill_incomplete_products.py

Options (edit at the top of __main__):
  DRY_RUN = True — prints what would be fixed, writes nothing
  LIMIT   = None   — set to an int to process only N products (useful for testing)
"""

from dotenv import load_dotenv
load_dotenv()

import sys
import os
import re
import time
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from firestore import (
    db,
    save_product_to_db,
    save_product_rating_to_db,
    save_percent_estimate_to_db,
    save_image_url_to_db,
    save_nutrition_to_db,
    get_ingredient_profile_from_db,
    save_ingredient_to_db,
)
from services.openfoodfacts_api import get_product_from_openfoodfacts
from services.barcode_resolver import resolve_product_name
from services.scrapers.bigbasket import (
    get_product_by_name as bb_get_product_by_name,
    get_product_image_url as bb_get_image_url,
)
from services.scrapers.blinkit import scrape_blinkit
from services.percent_estimate import get_percent_estimates
from utils.llm_client import get_ingredient_profile_from_llm, get_product_rating_from_llm
from utils.name_utils import clean_product_name
from utils.ingredient_utils import extract_ingredient_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Tuneables ─────────────────────────────────────────────────────────────────
DRY_RUN = False       # set True to preview without writing
LIMIT   = None         # set to int to cap how many products are processed
SLEEP_BETWEEN = 0.5   # seconds between products — be kind to APIs

# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_ingredients_from_raw(raw: str) -> list[str]:
    cleaned = re.sub(r"\(\d+\.?\d*%\)", "", raw)
    parts   = [p.strip() for p in cleaned.split(",")]
    return [p for p in parts if len(p) > 1 and not p.replace(".", "").isdigit()]


def _clean_name_for_search(name: str) -> str:
    name = re.sub(r",?\s*\d+\.?\d*\s*(g|kg|ml|l|oz|lb)\b", "", name, flags=re.IGNORECASE)
    name = name.replace("/", " ")
    name = re.sub(r"[,\-]+$", "", name).strip()
    return name


def _is_empty(value) -> bool:
    """True when a field is missing, None, empty string, empty list, or empty dict."""
    if value is None:
        return True
    if isinstance(value, (str,)) and value.strip() in ("", "Unknown"):
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def _audit(data: dict) -> dict[str, bool]:
    """
    Returns a dict of field → needs_fix (True = missing/incomplete).
    """
    return {
        "product_name":       _is_empty(data.get("product_name")),
        "ingredients":        _is_empty(data.get("ingredients")),
        "nutrients_per_100g": _is_empty(data.get("nutrients_per_100g")),
        "percent_estimate":   _is_empty(data.get("percent_estimate")),
        "product_rating":     _is_empty(data.get("product_rating")),
        "image_url":          _is_empty(data.get("image_url")),
    }


# ── Per-field fixers ──────────────────────────────────────────────────────────

def _resolve_name(barcode: str, current_name: str | None) -> str | None:
    """Try OFf → barcode_resolver. Returns None if nothing found."""
    off = get_product_from_openfoodfacts(barcode)
    if off:
        name = off.get("product_name", "").strip()
        if name and name != "Unknown":
            logger.info("  NAME     resolved via OFf: '%s'", name)
            return clean_product_name(name), off

    name = resolve_product_name(barcode)
    if name:
        logger.info("  NAME     resolved via barcode_resolver: '%s'", name)
        return clean_product_name(name), None

    return None, None


def _resolve_ingredients_and_nutrition(
    barcode: str,
    product_name: str,
    off_product: dict | None,
) -> tuple[list[str], dict, dict | None]:
    """
    Returns (ingredient_names, nutrition_data, raw_off_product).
    Tries OFf → BigBasket → Blinkit in order.
    """
    # ── OFf ───────────────────────────────────────────────────────────────────
    if off_product is None:
        off_product = get_product_from_openfoodfacts(barcode)

    if off_product:
        ingredients = [
            extract_ingredient_text(i)
            for i in off_product.get("ingredients", [])
            if extract_ingredient_text(i)
        ]
        nutriments = off_product.get("nutriments", {})
        nutrition  = {k: v for k, v in nutriments.items() if k.endswith("_100g")}
        if ingredients:
            logger.info("  INGR     %d ingredients from OFf", len(ingredients))
            return ingredients, nutrition, off_product

    # ── BigBasket ─────────────────────────────────────────────────────────────
    if product_name:
        search_name = _clean_name_for_search(product_name)
        bb_data = bb_get_product_by_name(search_name)
        if bb_data and bb_data.get("ingredients_raw"):
            ingredients = _parse_ingredients_from_raw(bb_data["ingredients_raw"])
            nutrition   = bb_data.get("nutrition") or {}
            if ingredients:
                logger.info("  INGR     %d ingredients from BigBasket", len(ingredients))
                return ingredients, nutrition, off_product

        # ── Blinkit ───────────────────────────────────────────────────────────
        blinkit_data = scrape_blinkit(product_name)
        if blinkit_data and blinkit_data.get("ingredients"):
            ingredients = blinkit_data["ingredients"]
            nutrition   = blinkit_data.get("nutrients_per_100g") or {}
            logger.info("  INGR     %d ingredients from Blinkit", len(ingredients))
            return ingredients, nutrition, off_product

    return [], {}, off_product


def _enrich_and_rate(
    barcode: str,
    ingredient_names: list[str],
    off_product: dict | None,
    dry_run: bool,
) -> tuple[list, list, dict]:
    """
    Returns (enriched_list, percent_estimates, product_rating).
    Writes ingredient profiles to Firestore unless dry_run.
    """
    enriched = []
    for name in ingredient_names:
        name = name.strip().lower()
        if not name:
            continue
        profile = get_ingredient_profile_from_db(name)
        if not profile:
            profile = get_ingredient_profile_from_llm(name)
            if profile and "error" not in profile and not dry_run:
                save_ingredient_to_db(name, name, profile)
        enriched.append({"name": name, "profile": profile})

    percent_estimates = get_percent_estimates(
        barcode, ingredient_names, product_data=off_product
    )

    product_rating = get_product_rating_from_llm(enriched, percent_estimates)
    return enriched, percent_estimates, product_rating


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(dry_run: bool = DRY_RUN, limit: int | None = LIMIT):
    docs = list(db.collection("products").stream())
    total = len(docs)
    logger.info("Found %d products in Firestore  (dry_run=%s  limit=%s)",
                total, dry_run, limit)

    stats = {"skipped": 0, "fixed": 0, "failed": 0, "already_complete": 0}
    processed = 0

    for doc in docs:
        if limit and processed >= limit:
            break

        barcode = doc.id
        data    = doc.to_dict()
        gaps    = _audit(data)
        needs_fix = [k for k, broken in gaps.items() if broken]

        if not needs_fix:
            stats["already_complete"] += 1
            continue

        processed += 1
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("BARCODE  %s  →  missing: %s", barcode, needs_fix)

        # Working copies of existing data
        product_name   = data.get("product_name", "").strip() or None
        ingredient_list: list[str] = [
            (i if isinstance(i, str) else i.get("name", ""))
            for i in data.get("ingredients", [])
            if (i if isinstance(i, str) else i.get("name", ""))
        ]
        nutrition_data = data.get("nutrients_per_100g") or {}
        off_product    = None
        fixed          = []

        try:
            # ── Fix name ──────────────────────────────────────────────────────
            if "product_name" in needs_fix:
                resolved_name, off_product = _resolve_name(barcode, product_name)
                if resolved_name:
                    product_name = resolved_name
                    if not dry_run:
                        db.collection("products").document(barcode).set(
                            {"product_name": product_name}, merge=True
                        )
                    fixed.append("product_name")
                else:
                    logger.warning("  NAME     could not resolve — skipping product")
                    stats["failed"] += 1
                    continue

            # ── Fix ingredients / nutrition ───────────────────────────────────
            if "ingredients" in needs_fix or "nutrients_per_100g" in needs_fix:
                resolved_ingredients, resolved_nutrition, off_product = \
                    _resolve_ingredients_and_nutrition(barcode, product_name, off_product)

                if resolved_ingredients and "ingredients" in needs_fix:
                    ingredient_list = resolved_ingredients
                    if not dry_run:
                        save_product_to_db(
                            barcode, product_name, ingredient_list,
                            resolved_nutrition or None,
                        )
                    fixed.append("ingredients")
                    if resolved_nutrition:
                        nutrition_data = resolved_nutrition
                        fixed.append("nutrients_per_100g")

                elif resolved_nutrition and "nutrients_per_100g" in needs_fix:
                    nutrition_data = resolved_nutrition
                    if not dry_run:
                        save_nutrition_to_db(barcode, nutrition_data)
                    fixed.append("nutrients_per_100g")

                if not ingredient_list:
                    logger.warning("  INGR     no ingredients resolved — skipping enrichment")
                    stats["failed"] += 1
                    continue

            # ── Fix image ─────────────────────────────────────────────────────
            if "image_url" in needs_fix and product_name:
                image_url = bb_get_image_url(product_name)
                if not dry_run:
                    save_image_url_to_db(barcode, image_url)
                fixed.append("image_url")
                logger.info("  IMAGE    → %s", image_url)

            # ── Fix percent_estimate / product_rating (require ingredients) ───
            need_estimate = "percent_estimate" in needs_fix
            need_rating   = "product_rating"   in needs_fix

            if (need_estimate or need_rating) and ingredient_list:
                enriched, percent_estimates, product_rating = _enrich_and_rate(
                    barcode, ingredient_list, off_product, dry_run
                )

                if need_estimate:
                    if not dry_run:
                        save_percent_estimate_to_db(barcode, percent_estimates)
                    fixed.append("percent_estimate")
                    logger.info("  PERCENT  %d values", len(percent_estimates))

                if need_rating:
                    if not dry_run and product_rating and "error" not in product_rating:
                        save_product_rating_to_db(barcode, product_rating)
                    fixed.append("product_rating")
                    score = product_rating.get("product_score", "?") if product_rating else "err"
                    logger.info("  RATING   score=%s", score)

            # ── Summary ───────────────────────────────────────────────────────
            if fixed:
                logger.info("  ✅  fixed: %s%s", fixed, "  [DRY RUN — not written]" if dry_run else "")
                stats["fixed"] += 1
            else:
                logger.info("  ⚠️   nothing could be fixed for %s", barcode)
                stats["skipped"] += 1

        except Exception as e:
            logger.error("  ❌  unhandled error for %s: %s", barcode, e)
            stats["failed"] += 1

        time.sleep(SLEEP_BETWEEN)

    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info(
        "DONE  total=%d  complete=%d  fixed=%d  skipped=%d  failed=%d",
        total,
        stats["already_complete"],
        stats["fixed"],
        stats["skipped"],
        stats["failed"],
    )


if __name__ == "__main__":
    run()