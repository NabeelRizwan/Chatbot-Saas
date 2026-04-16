import requests
import os

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY_2")

def generate_response(message, knowledge):
    context = "\n".join([k.content for k in knowledge]) if knowledge else ""

    # LIMIT CONTEXT SIZE (VERY IMPORTANT)
    context = context[:2000]

    prompt = f"""
    Answer based on this knowledge:
    {context}

    User: {message}
    """

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"

    headers = {
        "Content-Type": "application/json"
    }

    data = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ]
    }

    res = requests.post(url, headers=headers, json=data)
    result = res.json()

    return result["candidates"][0]["content"]["parts"][0]["text"]
