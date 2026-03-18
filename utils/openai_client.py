from groq import Groq
from utils.clean_json_output import parse_cleaned_json
import os

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def get_ingredient_details_from_openai(ingredient_name):
    ingredient_name = ingredient_name.lower()

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


def get_product_rating_from_gemini(ingredients, percent_estimate):
    if len(percent_estimate) < len(ingredients):
        percent_estimate += ["not avail"] * (len(ingredients) - len(percent_estimate))
    percent_estimate = percent_estimate[:len(ingredients)]

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
