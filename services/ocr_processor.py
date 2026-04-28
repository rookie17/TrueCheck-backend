"""
services/ocr_processor.py

Extracts barcode, product name, and ingredients from three OCR text blobs.

Strategy:
  - Heuristic-first (regex-based), Groq as fallback when heuristics are incomplete.
  - Set OCR_FORCE_GROQ_EXTRACTION=true in .env to skip heuristics entirely
    (useful for demos/evaluations where reliability matters more than speed).
"""

import os
import re
import logging

from utils.llm_client import client  # reuse existing Groq singleton
from utils.clean_json_output import parse_cleaned_json

logger = logging.getLogger(__name__)

# ── Config toggle ─────────────────────────────────────────────────────────────
# Set OCR_FORCE_GROQ_EXTRACTION=true in .env to bypass heuristics entirely.
FORCE_GROQ = os.getenv("OCR_FORCE_GROQ_EXTRACTION", "false").lower() == "true"

# ── Terminal keyword pattern ──────────────────────────────────────────────────
# Signals the end of the ingredients list on Indian packaged food labels.
_TERMINAL_KEYWORDS = [
    r"nutritional\s+(information|facts?|value)",
    r"nutrition\s+facts?",
    r"best\s+before",
    r"manufactured\s+by",
    r"marketed\s+by",
    r"packed\s+by",
    r"net\s+(weight|wt\.?|content)",
    r"mrp\b",
    r"allergen",
    r"storage\s+(instructions?|conditions?)",
    r"directions?\s+for\s+use",
    r"how\s+to\s+use",
    r"country\s+of\s+origin",
    r"fssai",
    r"batch\s+no",
    r"mfg\b",
    r"\bexp\b",
    r"customer\s+care",
    r"helpline",
]
_TERMINAL_RE = re.compile(
    r"(?i)\b(" + "|".join(_TERMINAL_KEYWORDS) + r")\b"
)


# ── Heuristic extractors ──────────────────────────────────────────────────────

def extract_barcode_from_ocr(ocr_text: str) -> str | None:
    """
    Finds digit sequences of length 8–14 (covers EAN-8, UPC-A, EAN-13).
    Prefers EAN-13 with Indian prefix 890; falls back to longest candidate.
    """
    candidates = re.findall(r"\b(\d{8,14})\b", ocr_text)
    if not candidates:
        return None

    indian_ean13 = [c for c in candidates if len(c) == 13 and c.startswith("890")]
    if indian_ean13:
        return indian_ean13[0]

    ean13 = [c for c in candidates if len(c) == 13]
    if ean13:
        return ean13[0]

    return max(candidates, key=len)


def extract_product_name_from_ocr(ocr_text: str) -> str | None:
    """
    Strips pure-digit/symbol lines and very short lines.
    Removes weight/volume suffixes, returns the longest surviving line.
    The name OCR is a dedicated photo so garbage is usually minimal.
    """
    lines = [l.strip() for l in ocr_text.splitlines() if l.strip()]

    candidates = []
    for line in lines:
        if len(line) < 3:
            continue
        if re.match(r"^[\d\s\W]+$", line):  # nothing but digits/symbols
            continue
        cleaned = re.sub(
            r"\b\d+\.?\d*\s*(g|kg|ml|l|oz|lb)\b", "", line, flags=re.IGNORECASE
        ).strip()
        if len(cleaned) > 2:
            candidates.append(cleaned)

    if not candidates:
        return None

    return max(candidates, key=len)


def extract_ingredients_from_ocr(ocr_text: str) -> list[str] | None:
    """
    Locates the 'Ingredients' header, slices the text that follows,
    terminates at any known label section keyword, then parses
    the comma-separated ingredient list.
    """
    match = re.search(r"(?i)\bingredients?\s*[:\-]?\s*", ocr_text)
    if not match:
        return None

    text_after = ocr_text[match.end():]

    # Truncate at first terminal keyword
    terminal = _TERMINAL_RE.search(text_after)
    if terminal:
        text_after = text_after[: terminal.start()]

    # Normalise whitespace, strip percentage annotations
    text_after = re.sub(r"\(\s*\d+\.?\d*\s*%\s*\)", "", text_after)
    text_after = re.sub(r"\s+", " ", text_after).strip()

    parts = [p.strip() for p in text_after.split(",")]
    ingredients = [
        p for p in parts
        if len(p) > 1 and not re.match(r"^[\d\s\W]+$", p)
    ]

    return ingredients if ingredients else None


# ── Groq extractor ────────────────────────────────────────────────────────────

_GROQ_SYSTEM_PROMPT = """\
You are an OCR text parser for Indian packaged food products.
You receive three OCR blobs photographed from different parts of the product:
  barcode_ocr     — photo of the barcode area (contains the printed barcode digits)
  name_ocr        — photo of the product front face (brand + product name)
  ingredients_ocr — photo of the back label (ingredients list)

Return ONLY valid JSON, no markdown fences, no explanation:
{
  "barcode":     "<8-14 digit EAN/UPC barcode, prefer Indian EAN-13 starting 890, or null>",
  "name":        "<clean brand + product name without weight/size, or null>",
  "ingredients": ["<ingredient1>", "<ingredient2>", ...]
}

Rules:
- barcode:     digits only, no spaces or dashes.
- name:        strip weights, volumes, MRP, and other label clutter.
- ingredients: actual ingredient names only — no percentages, no E-codes unless
               they are ingredient names, no label noise. Return [] if none found.
- Return null for barcode/name if genuinely undetectable.
"""


def _groq_extract_all(barcode_ocr: str, name_ocr: str, ingredients_ocr: str) -> dict:
    user_content = (
        f"barcode_ocr:\n{barcode_ocr}\n\n"
        f"name_ocr:\n{name_ocr}\n\n"
        f"ingredients_ocr:\n{ingredients_ocr}"
    )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": _GROQ_SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ],
        temperature=0.1,
    )

    return parse_cleaned_json(response.choices[0].message.content)


def _run_groq_extraction(barcode_ocr: str, name_ocr: str, ingredients_ocr: str) -> dict:
    try:
        result = _groq_extract_all(barcode_ocr, name_ocr, ingredients_ocr)
        result["extraction_method"] = "groq"
        logger.info(
            "OCR      Groq — barcode=%s  name=%s  ingredients=%d",
            result.get("barcode"),
            result.get("name"),
            len(result.get("ingredients") or []),
        )
        return result
    except Exception as e:
        logger.error("OCR      Groq extraction failed: %s", e)
        return {
            "barcode":          None,
            "name":             None,
            "ingredients":      None,
            "extraction_method": "groq_failed",
            "error":            str(e),
        }


# ── Public entry point ────────────────────────────────────────────────────────

def process_ocr_inputs(barcode_ocr: str, name_ocr: str, ingredients_ocr: str) -> dict:
    """
    Main entry point for OCR-based product scanning.

    Flow:
      1. If FORCE_GROQ → skip heuristics, call Groq directly.
      2. Otherwise run heuristic extractors on all three blobs.
      3. If barcode or ingredients are missing after heuristics → Groq fallback.
      4. Always cross-validate the barcode field with a digit-only regex
         to catch Groq hallucinations before the result leaves this function.

    Returns:
        {
            "barcode":          str | None,
            "product_name":     str | None,   # key is 'product_name' for consistency with main.py
            "ingredients":      list[str] | None,
            "extraction_method": "heuristic" | "groq" | "groq_failed"
        }
    """
    if FORCE_GROQ:
        logger.info("OCR      FORCE_GROQ=true — bypassing heuristics")
        raw = _run_groq_extraction(barcode_ocr, name_ocr, ingredients_ocr)
    else:
        logger.info("OCR      running heuristic extraction")
        barcode     = extract_barcode_from_ocr(barcode_ocr)
        name        = extract_product_name_from_ocr(name_ocr)
        ingredients = extract_ingredients_from_ocr(ingredients_ocr)

        logger.info(
            "OCR      heuristic — barcode=%s  name=%s  ingredients=%d",
            barcode, name, len(ingredients) if ingredients else 0,
        )

        if not barcode or not ingredients:
            logger.info("OCR      heuristic incomplete — falling back to Groq")
            raw = _run_groq_extraction(barcode_ocr, name_ocr, ingredients_ocr)
        else:
            raw = {
                "barcode":          barcode,
                "name":             name,
                "ingredients":      ingredients,
                "extraction_method": "heuristic",
            }

    # Cross-validate barcode: must be 8-14 digits only
    barcode = raw.get("barcode")
    if barcode and not re.fullmatch(r"\d{8,14}", str(barcode)):
        logger.warning("OCR      barcode validation failed ('%s') — setting to None", barcode)
        barcode = None

    return {
        "barcode":           barcode,
        "product_name":      raw.get("name") or raw.get("product_name"),
        "ingredients":       raw.get("ingredients"),
        "extraction_method": raw.get("extraction_method", "unknown"),
    }