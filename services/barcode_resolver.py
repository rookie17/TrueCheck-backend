"""
services/barcode_resolver.py
=============================
EAN barcode → product name using a free-first fallback chain:
  1. DuckDuckGo Instant Answer API (zero cost, no key, no quota)
  2. Google Custom Search API        (free 100 queries/day)

Why this works:
  Searching a barcode on Google returns product pages (BigBasket, Flipkart,
  Amazon, brand sites) that all have the product name in their page title.
  We extract the name from the first clean result title.

Setup (one-time, free):
  1. console.cloud.google.com → enable "Custom Search API"
  2. programmablesearchengine.google.com → create engine → add retail sites
  3. Add to .env:
       GOOGLE_SEARCH_API_KEY=your_api_key
       GOOGLE_SEARCH_ENGINE_ID=your_engine_id

Limits:
  - DuckDuckGo: no limit, no key (but won't always return a result)
  - Google CSE: 100 queries/day free, no credit card required
"""

import os
import re
import requests

_GOOGLE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
_DDG_URL = "https://api.duckduckgo.com/"

# Noise patterns commonly appended to product titles by retail sites
_TITLE_NOISE = re.compile(
    r"\s*[\|\-–—]\s*(buy|online|best price|order|shop|at|on|from|"
    r"bigbasket|blinkit|flipkart|zepto|jiomart|amazon|swiggy|instamart|"
    r"grofers|myntra|1mg|netmeds|pharmeasy).*$",
    re.IGNORECASE,
)

_JUNK_TITLES = re.compile(
    r"^(google|search results|404|page not found|just a moment|access denied)$",
    re.IGNORECASE,
)


def _clean_title(title: str) -> str:
    title = _TITLE_NOISE.sub("", title).strip()
    title = re.sub(r"[\|\-–—,:]+$", "", title).strip()
    return title


def _looks_like_product_name(title: str) -> bool:
    if not title or len(title) < 4:
        return False
    if _JUNK_TITLES.match(title):
        return False
    if re.match(r"^\d+$", title):
        return False
    return True


# ─────────────────────────────────────────────
# Source 1: DuckDuckGo Instant Answer (free, keyless)
# ─────────────────────────────────────────────

def get_product_name_from_duckduckgo(barcode: str) -> str | None:
    """
    Queries DuckDuckGo's instant answer API for the barcode.
    No API key required, no quota. Returns None if no usable result.

    Note: DDG instant answers are sparse — this won't always fire,
    but when it does it costs nothing and preserves Google quota.
    """
    try:
        response = requests.get(
            _DDG_URL,
            params={
                "q": barcode,
                "format": "json",
                "no_redirect": "1",
                "no_html": "1",
            },
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            },
            timeout=8,
        )

        if response.status_code != 200:
            print(f"[DDG] HTTP {response.status_code} for barcode {barcode}")
            return None

        data = response.json()

        # DDG returns a Heading + AbstractText for well-known entities
        heading = data.get("Heading", "").strip()
        if _looks_like_product_name(heading):
            cleaned = _clean_title(heading)
            if _looks_like_product_name(cleaned):
                print(f"[DDG] Resolved {barcode} → '{cleaned}'")
                return cleaned

        # Some barcodes surface in RelatedTopics
        for topic in data.get("RelatedTopics", []):
            text = topic.get("Text", "")
            if text:
                # Text is usually "Product Name - description", grab the first part
                candidate = text.split(" - ")[0].strip()
                candidate = _clean_title(candidate)
                if _looks_like_product_name(candidate):
                    print(f"[DDG] Resolved {barcode} → '{candidate}' (via RelatedTopics)")
                    return candidate

        print(f"[DDG] No usable result for barcode {barcode}")
        return None

    except requests.exceptions.Timeout:
        print(f"[DDG] Timeout for barcode {barcode}")
        return None
    except Exception as e:
        print(f"[DDG] Error for barcode {barcode}: {e}")
        return None


# ─────────────────────────────────────────────
# Source 2: Google Custom Search (100/day free)
# ─────────────────────────────────────────────

_SERPER_URL = "https://google.serper.dev/search"

def get_product_name_from_google(barcode: str) -> str | None:
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        print("[Serper] SERPER_API_KEY not set — skipping")
        return None

    try:
        response = requests.post(
            _SERPER_URL,
            headers={
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
            },
            json={"q": barcode, "num": 5},
            timeout=10,
        )

        if response.status_code != 200:
            print(f"[Serper] API error {response.status_code}: {response.text[:200]}")
            return None

        items = response.json().get("organic", [])
        for item in items:
            cleaned = _clean_title(item.get("title", ""))
            if _looks_like_product_name(cleaned):
                print(f"[Serper] Resolved {barcode} → '{cleaned}'")
                return cleaned

        print(f"[Serper] No usable result for barcode {barcode}")
        return None

    except Exception as e:
        print(f"[Serper] Error for barcode {barcode}: {e}")
        return None

# ─────────────────────────────────────────────
# Public interface: tries DDG → Google CSE
# ─────────────────────────────────────────────

def resolve_product_name(barcode: str) -> str | None:
    """
    Fallback chain for resolving a barcode to a product name:
      1. DuckDuckGo (free, keyless, no quota)
      2. Google Custom Search (100 queries/day)

    Returns the first successful result, or None if both fail.
    Called from main.py when OFf returns no product name.
    """
    name = get_product_name_from_duckduckgo(barcode)
    if name:
        return name

    return get_product_name_from_google(barcode)