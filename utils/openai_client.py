from config import GEMINI_API_KEY
import google.generativeai as genai
from utils.clean_json_output import parse_cleaned_json

# Configure the API
genai.configure(api_key=GEMINI_API_KEY)

# Create model instance
model = genai.GenerativeModel("gemini-2.0-flash")  

def get_ingredient_details_from_openai(ingredient_name):
    ingredient_name = ingredient_name.lower()
    
    with open("utils/system_prompt.txt", "r") as file:
        system_prompt = file.read()

    # Combine system and user prompts
    response = model.generate_content(
        [system_prompt, ingredient_name],
        generation_config={"temperature": 0.4}
    )

    return parse_cleaned_json(response.text)

def get_product_rating_from_gemini(ingredients, percent_estimate):
    # Pad percent_estimate if shorter than ingredients
    if len(percent_estimate) < len(ingredients):
        percent_estimate += ["not avail"] * (len(ingredients) - len(percent_estimate))
    
    # Trim if percent_estimate is longer
    percent_estimate = percent_estimate[:len(ingredients)]

    # Prepare input strings
    ingredients_str = f"ingredients = {ingredients}"
    estimates_str = f"percent_estimate = {percent_estimate}"

    # Load system prompt
    with open("utils/product_rating_prompt.txt", "r") as file:
        system_prompt = file.read()
    
    # Compose full prompt
    full_prompt = f"{system_prompt}\n\n{ingredients_str}\n{estimates_str}"
    
    # Call the model
    response = model.generate_content(
        [full_prompt],
        generation_config={"temperature": 0.2}
    )

    return parse_cleaned_json(response.text)
