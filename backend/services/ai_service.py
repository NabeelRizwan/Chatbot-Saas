import google.generativeai as genai
import os

# Configure Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Use a stable working model
model = genai.GenerativeModel("models/gemini-2.5-flash")

def generate_response(message, knowledge):
    context = "\n".join([k.content for k in knowledge]) if knowledge else ""
    context = context[:2000]

    prompt = f"""
    Answer based on this knowledge:
    {context}

    User: {message}
    """

    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print("ERROR:", str(e))
        return f"Gemini Error: {str(e)}"
