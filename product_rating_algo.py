from flask import Flask, request, jsonify


def count_ingredients(product_json):
    return len(product_json.get("ingredients", []))


def algorithm_1(ingredients):
    # Basic average of health_score
    scores = [i["profile"].get("health_score", 5) for i in ingredients if i.get("profile")]
    return sum(scores) / len(scores) if scores else 5


def algorithm_2(ingredients):
    # Weighted based on position (more weight to earlier ingredients)
    total_score = 0
    total_weight = 0
    for index, ing in enumerate(ingredients):
        score = ing["profile"].get("health_score", 5)
        weight = 1 / (index + 1)
        total_score += score * weight
        total_weight += weight
    return total_score / total_weight if total_weight > 0 else 5


def algorithm_3(ingredients):
    # Favor simpler (fewer ingredient) products
    base_score = algorithm_2(ingredients)
    ingredient_count = len(ingredients)
    if ingredient_count <= 3:
        return min(base_score + 1.0, 10.0)
    elif ingredient_count <= 6:
        return base_score
    else:
        return max(base_score - 1.0, 0.0)


def processed_product_score(product_json):
    ingredient_count = count_ingredients(product_json)
    ingredients = product_json.get("ingredients", [])

    score1 = algorithm_1(ingredients)
    score2 = algorithm_2(ingredients)
    score3 = algorithm_3(ingredients)

    final_score = round((score1 + score2 + score3) / 3, 2)

    return {
        "product_name": product_json.get("product_name", "Unknown"),
        "ingredient_count": ingredient_count,
        "scores": {
            "algorithm_1": round(score1, 2),
            "algorithm_2": round(score2, 2),
            "algorithm_3": round(score3, 2),
            "final_score": final_score
        }
    }
