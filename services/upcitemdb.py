import logging
import requests

logger = logging.getLogger(__name__)

UPCITEMDB_URL = "https://api.upcitemdb.com/prod/trial/lookup"


def get_product_name_from_barcode(barcode: str) -> str | None:
    """
    Look up a barcode on UPCitemdb and return the product title.
    Free tier: 100 req/day, no auth needed.
    Returns None if not found or on error.
    """
    try:
        resp = requests.get(
            UPCITEMDB_URL,
            params={"upc": barcode},
            headers={"User-Agent": "TrueCheck/1.0 (health analyzer app; contact@truecheck.app)"},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()

        items = data.get("items", [])
        if not items:
            logger.warning(f"UPCitemdb: no results for barcode {barcode}")
            return None

        item = items[0]
        name = item.get("title") or item.get("description")
        if not name and item.get("brand"):
            name = f"{item['brand']} {item.get('description', '')}".strip()

        return name or None

    except Exception as e:
        logger.error(f"UPCitemdb lookup failed for {barcode}: {e}")
        return None