def extract_ingredient_text(item: dict) -> str:
    text = item.get("text", "")
    if isinstance(text, dict):
        return text.get("en", "") or next(iter(text.values()), "")
    return text if isinstance(text, str) else ""