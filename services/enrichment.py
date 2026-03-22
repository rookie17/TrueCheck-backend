def enrich_ingredients(ingredient_names: list) -> list:
    """
    Returns ingredient names as a simple list.
    Profiles are handled by the ML pipeline now.
    """
    return [
        {"name": name.strip().lower()}
        for name in ingredient_names
        if name and name.strip()
    ]