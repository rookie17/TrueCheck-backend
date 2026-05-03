# utils/name_utils.py

import re

# Retail noise after pipe or dash
_TITLE_NOISE = re.compile(
    r"\s*[\|\-–—]\s*(buy|online|best price|order|shop|at|on|from|"
    r"bigbasket|blinkit|flipkart|zepto|jiomart|amazon|swiggy|instamart|"
    r"grofers|myntra|1mg|netmeds|pharmeasy|fetch\s*[n&]\s*buy).*$",
    re.IGNORECASE,
)

# Everything after a pipe regardless of what follows
_PIPE_SPLIT = re.compile(r"\s*\|.*$")

# Weight/size suffixes — "850 g", "1.2kg", "500ml", "450g/487.5g", "60.1 g"
_WEIGHT_SUFFIX = re.compile(
    r",?\s*\(?\d+[\d\./]*\s*(g|kg|ml|l|oz|lb)(\s*/\s*\d+[\d\.]*\s*(g|kg|ml|l|oz|lb))?\)?\s*$",
    re.IGNORECASE,
)

# Price artifacts — "5 MRP", "Rs. 40", "₹99", "MRP Rs.10"
_PRICE_NOISE = re.compile(
    r",?\s*(MRP\.?\s*)?(Rs\.?\s*\d+[\d\.]*|₹\s*\d+[\d\.]*|\d+\.?\d*\s*MRP)\b.*$",
    re.IGNORECASE,
)

# Scraper site names that bleed into titles
_SITE_NAMES = re.compile(
    r",?\s*(fetch\s*[n&]\s*buy|fetch\s*and\s*buy|buy\s*online|[a-z0-9-]+\.(com|in|co\.in))\b.*$",
    re.IGNORECASE,
)

# Standalone packaging words trailing the name (not mid-name)
_PACK_SUFFIX = re.compile(
    r",?\s*\b(pouch|pack|bottle|jar|box|can|sachet|carton|bag|tin|tub)\s*$",
    re.IGNORECASE,
)

# Scraper artifacts
_ARTIFACTS = re.compile(r"\s*(\.\.\.more|…more|more)$", re.IGNORECASE)

# Trailing punctuation/separators
_TRAILING_JUNK = re.compile(r"[\|\-–—,:\s]+$")

_MAX_LENGTH = 60


def clean_product_name(name: str) -> str:
    if not name or name == "Unknown":
        return name

    name = _PIPE_SPLIT.sub("", name)
    name = _TITLE_NOISE.sub("", name)
    name = _SITE_NAMES.sub("", name)
    name = _PRICE_NOISE.sub("", name)
    name = _ARTIFACTS.sub("", name)
    name = _WEIGHT_SUFFIX.sub("", name)
    name = _PACK_SUFFIX.sub("", name)
    name = _TRAILING_JUNK.sub("", name).strip()

    if len(name) > _MAX_LENGTH:
        name = name[:_MAX_LENGTH].rsplit(" ", 1)[0].strip()

    return name or "Unknown"