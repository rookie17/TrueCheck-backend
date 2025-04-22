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
