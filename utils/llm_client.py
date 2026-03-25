from groq import Groq
from utils.clean_json_output import parse_cleaned_json
import os

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def get_ingredient_profile_from_llm(ingredient_name: str) -> dict:
    """
    Uses Groq/LLaMA to generate a health profile for a single ingredient.
    Returns parsed JSON dict, or {"error": ...} on failure.
    """
    ingredient_name = ingredient_name.lower()

    try:
        with open("utils/system_prompt.txt", "r") as file:
            system_prompt = file.read()

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": ingredient_name}
            ],
            temperature=0.4
        )

        return parse_cleaned_json(response.choices[0].message.content)

    except Exception as e:
        return {"error": f"LLM ingredient profile failed: {str(e)}"}


def get_product_rating_from_llm(ingredients: list, percent_estimate: list) -> dict:
    """
    Uses Groq/LLaMA to generate an overall product health rating.
    Returns parsed JSON dict, or {"error": ...} on failure.
    """
    if len(percent_estimate) < len(ingredients):
        percent_estimate += ["not avail"] * (len(ingredients) - len(percent_estimate))
    percent_estimate = percent_estimate[:len(ingredients)]

    try:
        with open("utils/product_rating_prompt.txt", "r") as file:
            system_prompt = file.read()

        full_prompt = f"ingredients = {ingredients}\npercent_estimate = {percent_estimate}"

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": full_prompt}
            ],
            temperature=0.2
        )

        return parse_cleaned_json(response.choices[0].message.content)

    except Exception as e:
        return {"error": f"LLM product rating failed: {str(e)}"}
