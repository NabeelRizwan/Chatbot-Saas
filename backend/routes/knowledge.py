from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import SessionLocal
import models

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/add")
def add_knowledge(api_key: str, content: str, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).filter_by(api_key=api_key).first()
    if not customer:
        return {"error": "Invalid API key"}

    entry = models.Knowledge(customer_id=customer.id, content=content)
    db.add(entry)
    db.commit()
    return {"status": "added"}
