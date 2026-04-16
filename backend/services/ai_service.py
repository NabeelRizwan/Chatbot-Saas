from openai import OpenAI
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generate_response(message, knowledge):
    context = "\n".join([k.content for k in knowledge]) if knowledge else ""

    prompt = f"""
    Answer based on this knowledge:
    {context}

    User: {message}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content
