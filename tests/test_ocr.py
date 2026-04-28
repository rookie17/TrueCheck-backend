"""
tests/test_ocr.py

Tests for:
  - services/ocr_processor.py  (unit — heuristic extractors + process_ocr_inputs)
  - /scan-ocr route             (integration — Flask test client, all I/O mocked)

Run with:
  pytest tests/test_ocr.py -v
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from services.ocr_processor import (
    extract_barcode_from_ocr,
    extract_product_name_from_ocr,
    extract_ingredients_from_ocr,
    process_ocr_inputs,
)


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════

SAMPLE_BARCODE_OCR = """
LOT NO 44B
8901058861068
BEST BEFORE SEE PACK
"""

SAMPLE_NAME_OCR = """
Britannia NutriChoice
Digestive Biscuits
400g
"""

SAMPLE_INGREDIENTS_OCR = """
Ingredients: Wheat Flour (55%), Sugar, Edible Vegetable Oil,
Oat Flakes (5%), Wheat Bran (4%), Invert Syrup, Salt,
Raising Agents (503, 500).
Nutritional Information per 100g: Energy 462 kcal
"""

SAMPLE_DIRTY_INGREDIENTS_OCR = """
FSSAI Lic. No. 10013022002253
Mfd by Britannia Industries Ltd
INGRED1ENTS : Wheat Flour, Sugar, Edible 0il,
Oat Flakes, Salt, Baking Soda,
MRP Rs.40 (Incl. of all taxes)
Best Before: 6 months from mfg
"""

MOCK_INGREDIENT_PROFILE = {
    "ingredient_name": "wheat flour",
    "ingredient_profile": {
        "health_impact": "moderate",
        "category": "grain",
    }
}

MOCK_RATING = {
    "product_score": 72,
    "processing_level": "medium",
    "pros": ["contains oats"],
    "cons": ["high sugar"],
}


def _ocr_post_body(**overrides):
    base = {
        "barcode_ocr":     SAMPLE_BARCODE_OCR,
        "name_ocr":        SAMPLE_NAME_OCR,
        "ingredients_ocr": SAMPLE_INGREDIENTS_OCR,
    }
    base.update(overrides)
    return base


# ═════════════════════════════════════════════════════════════════════════════
# Unit — extract_barcode_from_ocr
# ═════════════════════════════════════════════════════════════════════════════

class TestExtractBarcode:

    def test_extracts_indian_ean13(self):
        result = extract_barcode_from_ocr("Ref 8901058861068 end")
        assert result == "8901058861068"

    def test_prefers_indian_prefix_over_generic_ean13(self):
        text = "Generic 1234567890123 Indian 8901234567890"
        result = extract_barcode_from_ocr(text)
        assert result == "8901234567890"

    def test_falls_back_to_generic_ean13(self):
        result = extract_barcode_from_ocr("Code 1234567890123")
        assert result == "1234567890123"

    def test_falls_back_to_ean8(self):
        result = extract_barcode_from_ocr("12345678 some noise")
        assert result == "12345678"

    def test_returns_none_for_no_digits(self):
        assert extract_barcode_from_ocr("No barcode here at all") is None

    def test_ignores_short_digit_sequences(self):
        # 7 digits is below EAN-8 threshold
        assert extract_barcode_from_ocr("1234567") is None

    def test_handles_garbled_surrounding_text(self):
        garbled = "L0T N0 44B\n8901058861068\nBEST BEF0RE SEE PACK"
        assert extract_barcode_from_ocr(garbled) == "8901058861068"

    def test_picks_longest_if_no_ean13(self):
        # Two EAN-8 candidates — picks the longest (both same length here),
        # or whichever max() returns; main thing is it returns something.
        result = extract_barcode_from_ocr("12345678 87654321")
        assert result is not None
        assert len(result) == 8


# ═════════════════════════════════════════════════════════════════════════════
# Unit — extract_product_name_from_ocr
# ═════════════════════════════════════════════════════════════════════════════

class TestExtractProductName:

    def test_returns_longest_meaningful_line(self):
        result = extract_product_name_from_ocr(SAMPLE_NAME_OCR)
        assert result is not None
        assert "Britannia" in result or "Digestive" in result

    def test_strips_weight_suffix(self):
        text = "Parle-G Biscuits 800g"
        result = extract_product_name_from_ocr(text)
        assert result is not None
        assert "800g" not in result

    def test_ignores_digit_only_lines(self):
        text = "8901058861068\n40.00\nParle-G Gold"
        result = extract_product_name_from_ocr(text)
        assert result == "Parle-G Gold"

    def test_returns_none_for_all_garbage(self):
        assert extract_product_name_from_ocr("123 456 *** !!!") is None

    def test_returns_none_for_empty(self):
        assert extract_product_name_from_ocr("") is None

    def test_ignores_very_short_lines(self):
        text = "OK\nBritannia NutriChoice Digestive"
        result = extract_product_name_from_ocr(text)
        assert "Britannia" in result


# ═════════════════════════════════════════════════════════════════════════════
# Unit — extract_ingredients_from_ocr
# ═════════════════════════════════════════════════════════════════════════════

class TestExtractIngredients:

    def test_extracts_basic_list(self):
        result = extract_ingredients_from_ocr(SAMPLE_INGREDIENTS_OCR)
        assert result is not None
        assert len(result) > 3
        assert any("Wheat Flour" in i for i in result)
        assert any("Sugar" in i for i in result)

    def test_terminates_at_nutritional_info(self):
        result = extract_ingredients_from_ocr(SAMPLE_INGREDIENTS_OCR)
        # "Energy 462 kcal" should not appear
        combined = " ".join(result)
        assert "Energy" not in combined
        assert "kcal" not in combined

    def test_strips_percentages(self):
        result = extract_ingredients_from_ocr(SAMPLE_INGREDIENTS_OCR)
        combined = " ".join(result)
        assert "%" not in combined

    def test_handles_garbled_header_spelling(self):
        # "INGRED1ENTS" — heuristic won't catch this; should return None
        result = extract_ingredients_from_ocr(SAMPLE_DIRTY_INGREDIENTS_OCR)
        assert result is None  # falls through to Groq in real flow

    def test_terminates_at_best_before(self):
        text = "Ingredients: Salt, Sugar, Water. Best Before: 6 months"
        result = extract_ingredients_from_ocr(text)
        assert result is not None
        assert not any("Best" in i or "Before" in i for i in result)

    def test_terminates_at_mrp(self):
        text = "Ingredients: Salt, Sugar\nMRP Rs.40"
        result = extract_ingredients_from_ocr(text)
        assert result is not None
        assert not any("MRP" in i for i in result)

    def test_terminates_at_fssai(self):
        text = "Ingredients: Salt, Sugar\nFSSAI Lic No 12345"
        result = extract_ingredients_from_ocr(text)
        assert result is not None
        assert not any("FSSAI" in i for i in result)

    def test_returns_none_when_no_ingredients_header(self):
        result = extract_ingredients_from_ocr("No header here, just some text")
        assert result is None

    def test_handles_colon_separator(self):
        result = extract_ingredients_from_ocr("Ingredients: Salt, Sugar")
        assert result == ["Salt", "Sugar"]

    def test_handles_dash_separator(self):
        result = extract_ingredients_from_ocr("Ingredients - Salt, Sugar")
        assert result == ["Salt", "Sugar"]

    def test_ignores_digit_only_tokens(self):
        text = "Ingredients: Salt, 503, Sugar, 500"
        result = extract_ingredients_from_ocr(text)
        # Standalone digits should be filtered
        assert result is not None
        assert "503" not in result
        assert "500" not in result


# ═════════════════════════════════════════════════════════════════════════════
# Unit — process_ocr_inputs (heuristic path)
# ═════════════════════════════════════════════════════════════════════════════

class TestProcessOcrInputs:

    def test_heuristic_success_returns_all_fields(self):
        result = process_ocr_inputs(
            SAMPLE_BARCODE_OCR, SAMPLE_NAME_OCR, SAMPLE_INGREDIENTS_OCR
        )
        assert result["barcode"] == "8901058861068"
        assert result["product_name"] is not None
        assert isinstance(result["ingredients"], list)
        assert len(result["ingredients"]) > 0
        assert result["extraction_method"] == "heuristic"

    def test_falls_back_to_groq_when_barcode_missing(self):
        groq_result = {
            "barcode": "8901058861068",
            "name": "Test Product",
            "ingredients": ["Salt", "Sugar"],
            "extraction_method": "groq",
        }
        with patch("services.ocr_processor._run_groq_extraction", return_value=groq_result):
            result = process_ocr_inputs(
                "no barcode here", SAMPLE_NAME_OCR, SAMPLE_INGREDIENTS_OCR
            )
        assert result["extraction_method"] == "groq"
        assert result["barcode"] == "8901058861068"

    def test_falls_back_to_groq_when_ingredients_missing(self):
        groq_result = {
            "barcode": "8901058861068",
            "name": "Test Product",
            "ingredients": ["Salt", "Sugar"],
            "extraction_method": "groq",
        }
        with patch("services.ocr_processor._run_groq_extraction", return_value=groq_result):
            result = process_ocr_inputs(
                SAMPLE_BARCODE_OCR, SAMPLE_NAME_OCR, "no header here at all"
            )
        assert result["extraction_method"] == "groq"

    def test_barcode_cross_validation_rejects_hallucination(self):
        # Groq returns a non-digit barcode — should be nulled out
        groq_result = {
            "barcode": "ABCD-1234",  # invalid
            "name": "Test Product",
            "ingredients": ["Salt"],
            "extraction_method": "groq",
        }
        with patch("services.ocr_processor._run_groq_extraction", return_value=groq_result):
            result = process_ocr_inputs("no barcode", SAMPLE_NAME_OCR, "no header")
        assert result["barcode"] is None

    def test_force_groq_env_bypasses_heuristics(self, monkeypatch):
        monkeypatch.setattr("services.ocr_processor.FORCE_GROQ", True)
        groq_result = {
            "barcode": "8901058861068",
            "name": "Forced Groq Product",
            "ingredients": ["Salt", "Sugar"],
            "extraction_method": "groq",
        }
        with patch("services.ocr_processor._run_groq_extraction", return_value=groq_result) as mock_groq:
            result = process_ocr_inputs(
                SAMPLE_BARCODE_OCR, SAMPLE_NAME_OCR, SAMPLE_INGREDIENTS_OCR
            )
        mock_groq.assert_called_once()
        assert result["extraction_method"] == "groq"

    def test_groq_failure_returns_safe_dict(self):
        with patch("services.ocr_processor._run_groq_extraction", return_value={
            "barcode": None,
            "name": None,
            "ingredients": None,
            "extraction_method": "groq_failed",
            "error": "connection timeout",
        }):
            result = process_ocr_inputs("no barcode", SAMPLE_NAME_OCR, "no header")
        assert result["barcode"] is None
        assert result["ingredients"] is None
        assert result["extraction_method"] == "groq_failed"


# ═════════════════════════════════════════════════════════════════════════════
# Integration — /scan-ocr route
# ═════════════════════════════════════════════════════════════════════════════

MOCK_EXTRACTED = {
    "barcode":          "8901058861068",
    "product_name":     "Britannia NutriChoice Digestive",
    "ingredients":      ["wheat flour", "sugar", "edible vegetable oil", "oat flakes"],
    "extraction_method": "heuristic",
}


def _patch_route_dependencies(extracted=None):
    """Returns a list of patches needed for the /scan-ocr route."""
    return [
        patch("main.process_ocr_inputs",           return_value=extracted or MOCK_EXTRACTED),
        patch("main.clean_product_name",            side_effect=lambda x: x),
        patch("main.save_product_to_db",            return_value=None),
        patch("main.get_ingredient_profile_from_db", return_value=MOCK_INGREDIENT_PROFILE),
        patch("main.save_ingredient_to_db",         return_value=None),
        patch("main.get_ingredient_profile_from_llm", return_value=MOCK_INGREDIENT_PROFILE),
        patch("main.get_percent_estimates",         return_value=["Not Available"] * 4),
        patch("main.get_product_rating_from_db",    return_value=None),
        patch("main.get_product_rating_from_llm",   return_value=MOCK_RATING),
        patch("main.save_product_rating_to_db",     return_value=None),
    ]


class TestScanOcrRoute:

    def test_happy_path_returns_200_and_correct_shape(self, client):
        patches = _patch_route_dependencies()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7], patches[8], patches[9]:
            resp = client.post(
                "/scan-ocr",
                json=_ocr_post_body(),
                content_type="application/json",
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert "product_name"        in data
        assert "ingredients_profile" in data
        assert "nutrients"           in data
        assert "percent_estimate"    in data
        assert "overall_rating"      in data
        assert "data_sources"        in data
        assert "ocr_meta"            in data

    def test_ingredients_profile_has_name_and_profile_keys(self, client):
        patches = _patch_route_dependencies()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7], patches[8], patches[9]:
            resp = client.post("/scan-ocr", json=_ocr_post_body())

        profiles = resp.get_json()["ingredients_profile"]
        assert len(profiles) > 0
        for item in profiles:
            assert "name"    in item
            assert "profile" in item

    def test_ocr_meta_reflects_barcode_recovery(self, client):
        patches = _patch_route_dependencies()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7], patches[8], patches[9]:
            resp = client.post("/scan-ocr", json=_ocr_post_body())

        meta = resp.get_json()["ocr_meta"]
        assert meta["barcode_recovered"] is True
        assert meta["extraction_method"] == "heuristic"

    def test_missing_ingredients_ocr_returns_400(self, client):
        resp = client.post(
            "/scan-ocr",
            json={"barcode_ocr": "test", "name_ocr": "test"},
        )
        assert resp.status_code == 400

    def test_non_json_body_returns_400(self, client):
        resp = client.post(
            "/scan-ocr",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400

    def test_empty_body_returns_400(self, client):
        resp = client.post("/scan-ocr", json={})
        assert resp.status_code == 400

    def test_extraction_failure_returns_422(self, client):
        failed_extraction = {
            "barcode":          None,
            "product_name":     None,
            "ingredients":      None,
            "extraction_method": "groq_failed",
        }
        patches = _patch_route_dependencies(extracted=failed_extraction)
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7], patches[8], patches[9]:
            resp = client.post(
                "/scan-ocr",
                json=_ocr_post_body(ingredients_ocr="total garbage no header"),
            )

        assert resp.status_code == 422

    def test_no_barcode_skips_product_save_and_rating_cache(self, client):
        no_barcode = {**MOCK_EXTRACTED, "barcode": None}
        patches = _patch_route_dependencies(extracted=no_barcode)
        with patches[0], patches[1], \
             patch("main.save_product_to_db")       as mock_save_product, \
             patches[3], patches[4], patches[5], patches[6], \
             patch("main.get_product_rating_from_db") as mock_get_rating, \
             patches[8], \
             patch("main.save_product_rating_to_db") as mock_save_rating:

            resp = client.post("/scan-ocr", json=_ocr_post_body())

        assert resp.status_code == 200
        mock_save_product.assert_not_called()
        mock_get_rating.assert_not_called()
        mock_save_rating.assert_not_called()
        assert resp.get_json()["ocr_meta"]["barcode_recovered"] is False

    def test_rating_loaded_from_firestore_when_barcode_present(self, client):
        cached_rating = {**MOCK_RATING, "product_score": 85}
        patches = _patch_route_dependencies()

        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], \
             patch("main.get_product_rating_from_db", return_value=cached_rating) as mock_get_rating, \
             patch("main.get_product_rating_from_llm") as mock_llm_rating, \
             patches[9]:

            resp = client.post("/scan-ocr", json=_ocr_post_body())

        assert resp.status_code == 200
        mock_get_rating.assert_called_once()
        mock_llm_rating.assert_not_called()
        assert resp.get_json()["overall_rating"]["product_score"] == 85

    def test_nutrients_field_is_empty_dict(self, client):
        # OCR never has nutrition data — nutrients must be {} not None
        patches = _patch_route_dependencies()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7], patches[8], patches[9]:
            resp = client.post("/scan-ocr", json=_ocr_post_body())

        assert resp.get_json()["nutrients"] == {}

    def test_data_sources_reflects_ocr_method(self, client):
        patches = _patch_route_dependencies()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7], patches[8], patches[9]:
            resp = client.post("/scan-ocr", json=_ocr_post_body())

        sources = resp.get_json()["data_sources"]
        assert "ocr" in sources["ingredients"]
        assert "ocr" in sources["product"]