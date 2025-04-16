from config import OPENAI_API_KEY

from openai import OpenAI

client = OpenAI(api_key=OPENAI_API_KEY)

def get_ingredient_details_from_openai(ingredient_name):
    prompt = f"""
You are a health analyst AI. Rate the following ingredient based on health effects.

Ingredient: {ingredient_name}

Give your answer in JSON format with these keys:
- pros
- cons
- health_score (1-10)
- description
    """
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful assistant that gives structured ingredient health analysis."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )

    return response.choices[0].message.content
