from fastapi import APIRouter, Depends, Header, Path
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import User
from schemas.schemas import BotCreate, BotDeleteResponse, BotResponse, BotUpdate
from services.auth_service import get_current_user
from services.bot_service import create_bot as create_bot_record
from services.bot_service import delete_bot as delete_bot_record
from services.bot_service import get_bot as get_bot_record
from services.bot_service import list_bots as list_bot_records
from services.bot_service import update_bot as update_bot_record

router = APIRouter()
collection_router = APIRouter()


@router.post("/create", response_model=BotResponse)
def create_bot(data: BotCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return create_bot_record(db, data, user=current_user)


@collection_router.get("/bots", response_model=list[BotResponse])
def get_bots(
    x_organization_id: int | None = Header(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_bot_records(db, user=current_user, organization_id=x_organization_id)


@router.get("/{bot_id}", response_model=BotResponse)
def get_bot(
    bot_id: int = Path(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_bot_record(db, bot_id, user=current_user)


@router.put("/{bot_id}", response_model=BotResponse)
def update_bot(
    data: BotUpdate,
    bot_id: int = Path(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return update_bot_record(db, bot_id, data, user=current_user)


@router.delete("/{bot_id}", response_model=BotDeleteResponse)
def delete_bot(
    bot_id: int = Path(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return delete_bot_record(db, bot_id, user=current_user)


@router.post("/{bot_id}/clone", response_model=BotResponse)
def clone_bot(
    bot_id: int = Path(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from services.bot_service import clone_bot as clone_bot_record
    return clone_bot_record(db, bot_id, user=current_user)
