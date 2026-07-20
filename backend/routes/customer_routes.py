import secrets

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Customer, User
from schemas.schemas import CustomerCreate, CustomerResponse
from services.auth_service import get_current_user

router = APIRouter()


@router.post("/create", response_model=CustomerResponse)
def create_customer(
    data: CustomerCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.customer_id:
        customer = db.query(Customer).filter(Customer.id == current_user.customer_id).first()
        if customer:
            return {"api_key": customer.api_key}

    api_key = secrets.token_hex(16)

    customer = Customer(name=data.name, api_key=api_key)
    db.add(customer)
    db.flush()
    current_user.customer_id = customer.id
    db.commit()
    db.refresh(customer)

    return {"api_key": api_key}
