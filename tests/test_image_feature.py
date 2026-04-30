"""
tests/test_image_feature.py
Tests for the image_url feature across bigbasket scraper, firestore, and main endpoint.
Run from project root: pytest tests/test_image_feature.py -v
"""

import pytest
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────────────────────
# services/scrapers/bigbasket.py — get_product_image_url
# ─────────────────────────────────────────────────────────────

class TestGetProductImageUrl:

    def setup_method(self):
        from services.scrapers.bigbasket import _PLACEHOLDER_URL
        self.placeholder = _PLACEHOLDER_URL

    def _make_product(self, images):
        return [{"images": images, "absolute_url": "/pd/123/test/"}]

    @patch("services.scrapers.bigbasket.search_by_name")
    def test_returns_medium_image_url(self, mock_search):
        mock_search.return_value = self._make_product([{
            "s": "https://bbassets.com/s.jpg",
            "m": "https://bbassets.com/m.jpg",
            "l": "https://bbassets.com/l.jpg",
        }])

        from services.scrapers.bigbasket import get_product_image_url
        result = get_product_image_url("Amul Butter")

        assert result == "https://bbassets.com/m.jpg"

    @patch("services.scrapers.bigbasket.search_by_name")
    def test_falls_back_to_large_if_no_medium(self, mock_search):
        mock_search.return_value = self._make_product([{
            "s": "https://bbassets.com/s.jpg",
            "l": "https://bbassets.com/l.jpg",
        }])

        from services.scrapers.bigbasket import get_product_image_url
        result = get_product_image_url("Amul Butter")

        assert result == "https://bbassets.com/l.jpg"

    @patch("services.scrapers.bigbasket.search_by_name")
    def test_returns_placeholder_when_no_results(self, mock_search):
        mock_search.return_value = []

        from services.scrapers.bigbasket import get_product_image_url
        result = get_product_image_url("Nonexistent Product XYZ")

        assert result == self.placeholder

    @patch("services.scrapers.bigbasket.search_by_name")
    def test_returns_placeholder_when_images_key_missing(self, mock_search):
        mock_search.return_value = [{"absolute_url": "/pd/123/test/"}]  # no "images" key

        from services.scrapers.bigbasket import get_product_image_url
        result = get_product_image_url("Some Product")

        assert result == self.placeholder

    @patch("services.scrapers.bigbasket.search_by_name")
    def test_returns_placeholder_when_images_list_empty(self, mock_search):
        mock_search.return_value = self._make_product([])

        from services.scrapers.bigbasket import get_product_image_url
        result = get_product_image_url("Some Product")

        assert result == self.placeholder

    @patch("services.scrapers.bigbasket.search_by_name")
    def test_returns_placeholder_on_exception(self, mock_search):
        mock_search.side_effect = Exception("BB is down")

        from services.scrapers.bigbasket import get_product_image_url
        result = get_product_image_url("Some Product")

        assert result == self.placeholder

    @patch("services.scrapers.bigbasket.search_by_name")
    def test_returns_placeholder_when_all_size_keys_missing(self, mock_search):
        mock_search.return_value = self._make_product([{"xl": "https://bbassets.com/xl.jpg"}])

        from services.scrapers.bigbasket import get_product_image_url
        result = get_product_image_url("Some Product")

        assert result == self.placeholder


# ─────────────────────────────────────────────────────────────
# firestore.py — image_url in save/get
# ─────────────────────────────────────────────────────────────

class TestFirestoreImageUrl:

    def _make_mock_db(self):
        mock_db = MagicMock()
        return mock_db

    @patch("firestore.db")
    def test_save_product_persists_image_url(self, mock_db):
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        from firestore import save_product_to_db
        save_product_to_db("1234567890", "Test Product", ["sugar", "salt"],
                           nutrition_data=None, image_url="https://bbassets.com/m.jpg")

        call_args = mock_db.collection.return_value.document.return_value.set.call_args
        saved_data = call_args[0][0]
        assert saved_data.get("image_url") == "https://bbassets.com/m.jpg"

    @patch("firestore.db")
    def test_save_product_skips_image_url_when_none(self, mock_db):
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        from firestore import save_product_to_db
        save_product_to_db("1234567890", "Test Product", ["sugar"])

        call_args = mock_db.collection.return_value.document.return_value.set.call_args
        saved_data = call_args[0][0]
        assert "image_url" not in saved_data

    @patch("firestore.db")
    def test_get_product_returns_image_url(self, mock_db):
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            "product_name": "Test Product",
            "ingredients": ["sugar"],
            "nutrients_per_100g": {},
            "image_url": "https://bbassets.com/m.jpg",
        }
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        from firestore import get_product_from_db
        result = get_product_from_db("1234567890")

        assert result["image_url"] == "https://bbassets.com/m.jpg"

    @patch("firestore.db")
    def test_get_product_returns_none_image_url_when_not_cached(self, mock_db):
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            "product_name": "Old Product",
            "ingredients": ["sugar"],
            "nutrients_per_100g": {},
            # no image_url key — simulates product cached before this feature
        }
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        from firestore import get_product_from_db
        result = get_product_from_db("1234567890")

        assert result["image_url"] is None

    @patch("firestore.db")
    def test_save_image_url_to_db(self, mock_db):
        from firestore import save_image_url_to_db
        save_image_url_to_db("1234567890", "https://bbassets.com/m.jpg")

        mock_db.collection.return_value.document.return_value.set.assert_called_once_with(
            {"image_url": "https://bbassets.com/m.jpg"}, merge=True
        )


# ─────────────────────────────────────────────────────────────
# main.py — /get-complete-product-info returns image_url
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from main import app
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


MOCK_RATING = {"product_score": 7, "pros": [], "cons": []}
MOCK_INGREDIENT_PROFILE = {"ingredient_profile": {"safety": "safe"}}


class TestMainEndpointImageUrl:

    @patch("main.get_product_rating_from_db", return_value=MOCK_RATING)
    @patch("main.get_percent_estimates", return_value=["Not Available"])
    @patch("main.get_ingredient_profile_from_db", return_value=MOCK_INGREDIENT_PROFILE)
    @patch("main.save_image_url_to_db")
    @patch("main.bb_get_image_url", return_value="https://bbassets.com/m.jpg")
    @patch("main.get_product_from_db")
    def test_cache_hit_with_existing_image_url(
        self, mock_get_product, mock_bb_image, mock_save_img,
        mock_get_profile, mock_percent, mock_rating, client
    ):
        """Cache hit with image_url already stored — should not call BB."""
        mock_get_product.return_value = {
            "product_name": "Amul Butter",
            "ingredients": [{"name": "butter", "profile": None}],
            "nutrients_per_100g": {},
            "image_url": "https://bbassets.com/cached.jpg",
        }

        resp = client.get("/get-complete-product-info?barcode=8901030874062")
        data = resp.get_json()

        assert resp.status_code == 200
        assert data["image_url"] == "https://bbassets.com/cached.jpg"
        mock_bb_image.assert_not_called()
        mock_save_img.assert_not_called()

    @patch("main.get_product_rating_from_db", return_value=MOCK_RATING)
    @patch("main.get_percent_estimates", return_value=["Not Available"])
    @patch("main.get_ingredient_profile_from_db", return_value=MOCK_INGREDIENT_PROFILE)
    @patch("main.save_image_url_to_db")
    @patch("main.bb_get_image_url", return_value="https://bbassets.com/m.jpg")
    @patch("main.get_product_from_db")
    def test_cache_hit_without_image_url_fetches_and_backfills(
        self, mock_get_product, mock_bb_image, mock_save_img,
        mock_get_profile, mock_percent, mock_rating, client
    ):
        """Cache hit but no image_url — should fetch from BB and backfill."""
        mock_get_product.return_value = {
            "product_name": "Amul Butter",
            "ingredients": [{"name": "butter", "profile": None}],
            "nutrients_per_100g": {},
            "image_url": None,
        }

        resp = client.get("/get-complete-product-info?barcode=8901030874062")
        data = resp.get_json()

        assert resp.status_code == 200
        assert data["image_url"] == "https://bbassets.com/m.jpg"
        mock_bb_image.assert_called_once_with("Amul Butter")
        mock_save_img.assert_called_once_with("8901030874062", "https://bbassets.com/m.jpg")

    @patch("main.save_product_to_db")
    @patch("main.get_product_rating_from_db", return_value=MOCK_RATING)
    @patch("main.get_percent_estimates", return_value=["Not Available"])
    @patch("main.get_ingredient_profile_from_db", return_value=MOCK_INGREDIENT_PROFILE)
    @patch("main.bb_get_image_url", return_value="https://bbassets.com/m.jpg")
    @patch("main.bb_get_product_by_name")
    @patch("main.resolve_product_name", return_value="Amul Butter")
    @patch("main.get_product_from_openfoodfacts", return_value=None)
    @patch("main.get_product_from_db", return_value=None)
    def test_cache_miss_saves_image_url_with_product(
        self, mock_get_product, mock_off, mock_resolve,
        mock_bb_product, mock_bb_image, mock_get_profile,
        mock_percent, mock_rating, mock_save_product, client
    ):
        """Cache miss — image should be fetched and passed to save_product_to_db."""
        mock_bb_product.return_value = {
            "ingredients_raw": "sugar, salt, water",
            "nutrition": {},
        }

        resp = client.get("/get-complete-product-info?barcode=8901030874062")
        data = resp.get_json()

        assert resp.status_code == 200
        assert data["image_url"] == "https://bbassets.com/m.jpg"

        call_kwargs = mock_save_product.call_args[1]
        assert call_kwargs.get("image_url") == "https://bbassets.com/m.jpg"

    @patch("main.get_product_rating_from_db", return_value=MOCK_RATING)
    @patch("main.get_percent_estimates", return_value=["Not Available"])
    @patch("main.get_ingredient_profile_from_db", return_value=MOCK_INGREDIENT_PROFILE)
    @patch("main.save_image_url_to_db")
    @patch("main.bb_get_image_url", return_value="https://placehold.co/300x300/eeeeee/999999?text=Image+Not+Available")
    @patch("main.get_product_from_db")
    def test_placeholder_returned_when_bb_finds_nothing(
        self, mock_get_product, mock_bb_image, mock_save_img,
        mock_get_profile, mock_percent, mock_rating, client
    ):
        """BB returns placeholder — it should still be set and cached."""
        mock_get_product.return_value = {
            "product_name": "Unknown Snack",
            "ingredients": [{"name": "salt", "profile": None}],
            "nutrients_per_100g": {},
            "image_url": None,
        }

        resp = client.get("/get-complete-product-info?barcode=0000000000001")
        data = resp.get_json()

        assert resp.status_code == 200
        assert "placehold.co" in data["image_url"]
        mock_save_img.assert_called_once()