from config import OPENAI_API_KEY
from openai import OpenAI

client = OpenAI(api_key=OPENAI_API_KEY)

def get_ingredient_details_from_openai(ingredient_name):

    with open("system_prompt.txt", "r") as file:
        system_prompt = file.read()


    user_prompt = ingredient_name

    # Send to OpenAI
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.4 
    )

    return response.choices[0].message.content
