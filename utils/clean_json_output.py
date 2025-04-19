import json
import re

def clean_gemini_response(raw_text: str):
    # Remove markdown-style wrapping and leading `json\n` or triple backticks
    cleaned = re.sub(r"^(```json|```)?", "", raw_text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"(```)$", "", cleaned.strip())
    cleaned = cleaned.strip()

    # Remove leading 'json\n' if still there
    if cleaned.lower().startswith("json\\n") or cleaned.lower().startswith("json\n"):
        cleaned = cleaned.split("\n", 1)[1]

    return cleaned

def parse_cleaned_json(raw_text: str):
    cleaned = clean_gemini_response(raw_text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "error": "JSON parsing failed",
            "raw": cleaned
        }
