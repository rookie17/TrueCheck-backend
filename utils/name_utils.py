import re

# Retail noise after pipe or dash
_TITLE_NOISE = re.compile(
    r"\s*[\|\-–—]\s*(buy|online|best price|order|shop|at|on|from|"
    r"bigbasket|blinkit|flipkart|zepto|jiomart|amazon|swiggy|instamart|"
    r"grofers|myntra|1mg|netmeds|pharmeasy).*$",
    re.IGNORECASE,
)

# Everything after a pipe regardless of what follows
_PIPE_SPLIT = re.compile(r"\s*\|.*$")

# Weight/size suffixes — "850 g", "1.2kg", "500ml", "450g/487.5g", "60.1 g"
_WEIGHT_SUFFIX = re.compile(
    r",?\s*\(?\d+[\d\./]*\s*(g|kg|ml|l|oz|lb)(\s*/\s*\d+[\d\.]*\s*(g|kg|ml|l|oz|lb))?\)?\s*$",
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
    name = _ARTIFACTS.sub("", name)
    name = _WEIGHT_SUFFIX.sub("", name)
    name = _TRAILING_JUNK.sub("", name).strip()

    if len(name) > _MAX_LENGTH:
        name = name[:_MAX_LENGTH].rsplit(" ", 1)[0].strip()

    return name or "Unknown"