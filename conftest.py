"""
conftest.py — place this in your project root.

Mocks firebase_admin at the sys.modules level BEFORE any app code is imported,
so tests run without real Firebase credentials.
"""

import sys
import os
from unittest.mock import MagicMock

# ── Block Firebase initialisation ─────────────────────────────────────────────
_firebase_mock = MagicMock()
sys.modules["firebase_admin"]                      = _firebase_mock
sys.modules["firebase_admin.credentials"]          = _firebase_mock.credentials
sys.modules["firebase_admin.firestore"]            = _firebase_mock.firestore
sys.modules["google.cloud.firestore_v1"]           = MagicMock()
sys.modules["google.cloud.firestore_v1.base_query"] = MagicMock()

# ── Dummy env vars so os.getenv checks don't raise ───────────────────────────
os.environ.setdefault("GROQ_API_KEY",               "test-key")
os.environ.setdefault("FIREBASE_CREDENTIALS_PATH",  "fake/path.json")
os.environ.setdefault("GOOGLE_SEARCH_API_KEY",      "test-search-key")
os.environ.setdefault("GOOGLE_SEARCH_ENGINE_ID",    "test-engine-id")
os.environ.setdefault("OCR_FORCE_GROQ_EXTRACTION",  "false")

import pytest

@pytest.fixture(scope="session")
def app():
    from main import app as flask_app
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()