from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import SessionLocal
import models
from utils.security import generate_api_key

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/create")
def create_customer(name: str, db: Session = Depends(get_db)):
    api_key = generate_api_key()
    customer = models.Customer(name=name, api_key=api_key)
    db.add(customer)
    db.commit()
    return {"api_key": api_key}
