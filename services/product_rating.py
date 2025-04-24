class InvalidIngredientData(Exception):
    pass

def calculate_product_score(ingredients):
    if not ingredients or not isinstance(ingredients, list):
        raise InvalidIngredientData("Invalid ingredients format. Expected a list.")

    print("\n=== DEBUG: Starting Product Scoring ===")
    
    # Initialize scores
    scores = {
        'protein': 0,
        'fiber': 0,
        'saturated_fat': 0,
        'sugars': 0,
        'salt': 0,
        'processing': 0,
        'allergen': 0
    }

    # Process each ingredient
    for ingredient in ingredients:
        if not isinstance(ingredient, dict):
            print(f"Warning: Skipping invalid ingredient format: {ingredient}")
            continue

        # Extract nutritional data
        protein = float(ingredient.get('protein', 0))
        fiber = float(ingredient.get('fiber', 0))
        saturated_fat = float(ingredient.get('saturated_fat', 0))
        sugars = float(ingredient.get('sugars', 0))
        salt = float(ingredient.get('salt', 0))
        
        # Update scores
        scores['protein'] += protein
        scores['fiber'] += fiber
        scores['saturated_fat'] += saturated_fat
        scores['sugars'] += sugars
        scores['salt'] += salt

        # Check for allergens
        if ingredient.get('is_allergen', False):
            scores['allergen'] += 1

        # Check processing level
        processing_level = ingredient.get('processing_level', 0)
        scores['processing'] = max(scores['processing'], processing_level)

    # Calculate weighted scores
    weights = {
        'protein': 0.2,
        'fiber': 0.2,
        'saturated_fat': -0.15,
        'sugars': -0.15,
        'salt': -0.1,
        'processing': -0.1,
        'allergen': -0.1
    }

    weighted_scores = {}
    for component, score in scores.items():
        weighted_scores[component] = score * weights[component]
        print(f"\n{component} score: {score} (weighted: {weighted_scores[component]})")

    # Calculate final score (0-10)
    final_score = sum(weighted_scores.values())
    
    # Apply ingredient count bonus
    ingredient_count = len(ingredients)
    if ingredient_count <= 3:
        final_score = min(10, final_score * 1.2)  # 20% boost for simple products
        print(f"\nApplying 20% boost for simple product ({ingredient_count} ingredients)")
    elif ingredient_count >= 15:
        final_score = max(0, final_score * 0.9)  # 10% penalty for complex products
        print(f"\nApplying 10% penalty for complex product ({ingredient_count} ingredients)")

    # Normalize to 0-10 range
    final_score = max(0, min(10, round(final_score, 2)))
    print(f"\nFinal score: {final_score}")

    return {
        'final_score': final_score,
        'breakdown': {
            component: round(score, 2) for component, score in weighted_scores.items()
        }
    }
