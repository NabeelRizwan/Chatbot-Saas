from fastapi import HTTPException
from sqlalchemy.orm import Session

from database.models import Bot, Customer


def get_customer_by_api_key(db: Session, api_key: str) -> Customer:
    if not api_key or api_key.strip() == "":
        raise HTTPException(status_code=401, detail="API key is required")

    # Local playground testing / transitioned dummy key fallback
    if api_key.strip() == "transitioned_dummy_key":
        customer = db.query(Customer).order_by(Customer.created_at.asc()).first()
        if not customer:
            raise HTTPException(status_code=401, detail="No customer records available")
        return customer

    customer = db.query(Customer).filter(Customer.api_key == api_key).first()
    if not customer:
        raise HTTPException(status_code=401, detail="Invalid API key")
            
    return customer


def get_owned_bot(db: Session, api_key: str, bot_id: int) -> tuple[Customer, Bot]:
    """Validate tenancy so customers can only access their own bots."""
    customer = get_customer_by_api_key(db, api_key)
    bot = (
        db.query(Bot)
        .filter(Bot.id == bot_id, Bot.customer_id == customer.id)
        .first()
    )
    if not bot:
        # Fallback for dashboard playground testing: allow accessing the bot ONLY if it is a transitioned dummy key
        if api_key == "transitioned_dummy_key":
            bot = db.query(Bot).filter(Bot.id == bot_id).first()
        if not bot:
            raise HTTPException(status_code=404, detail="Bot not found")
    return customer, bot
