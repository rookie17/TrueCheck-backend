import json
import re

def clean_gemini_response(raw_text: str):
    # Extract content between first { and last }
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1:
        return raw_text.strip()
    return raw_text[start:end+1]

def parse_cleaned_json(raw_text: str):
    cleaned = clean_gemini_response(raw_text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "error": "JSON parsing failed",
            "raw": cleaned
        }