from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import get_db
from models import Customer, Knowledge
from services.ai_service import generate_response

router = APIRouter()

# ✅ Request model (FIXES 422 ERROR)
class ChatRequest(BaseModel):
    api_key: str
    message: str


@router.post("/")
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    # 🔑 1. Validate API key
    customer = db.query(Customer).filter(Customer.api_key == req.api_key).first()

    if not customer:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # 📚 2. Get knowledge for that customer
    knowledge = db.query(Knowledge).filter(Knowledge.customer_id == customer.id).all()

    # 🤖 3. Generate AI response
    try:
        reply = generate_response(req.message, knowledge)
    except Exception as e:
        print("AI ERROR:", e)
        raise HTTPException(status_code=500, detail="AI generation failed")

    # 📤 4. Return response
    return {
        "reply": reply
    }
