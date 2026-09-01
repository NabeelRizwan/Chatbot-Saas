from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import User
from schemas.schemas import AnalyticsSummaryResponse
from services.analytics_service import (
    get_bot_analytics_summary,
    get_organization_analytics_details,
)
from services.auth_service import get_optional_user
from services.bot_service import get_bot_or_404
from services.organization_service import require_org_role


router = APIRouter()


@router.get("/bot/{bot_id}/summary", response_model=AnalyticsSummaryResponse)
def get_bot_summary(
    bot_id: int = Path(..., gt=0),
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    get_bot_or_404(db, bot_id, user=current_user)
    return get_bot_analytics_summary(db, bot_id)


@router.get("/organization/{organization_id}/details")
def get_organization_details(
    organization_id: int = Path(..., gt=0),
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    require_org_role(db, current_user, organization_id, "member")
    return get_organization_analytics_details(db, organization_id)
