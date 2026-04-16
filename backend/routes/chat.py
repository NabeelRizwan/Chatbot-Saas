from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import SessionLocal
import models
from services.ai_service import generate_response

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/")
def chat(api_key: str, message: str, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).filter_by(api_key=api_key).first()
    if not customer:
        return {"error": "Invalid API key"}

    knowledge = db.query(models.Knowledge).filter_by(customer_id=customer.id).all()

    reply = generate_response(message, knowledge)

    return {"reply": reply}
