from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Plan, User
from schemas.schemas import PlanResponse, SubscriptionResponse, UsageSummaryResponse
from services.auth_service import get_current_user
from services.billing_service import BillingProvider, ensure_default_plans, serialize_plan, serialize_subscription
from services.organization_service import require_org_role
from services.usage_service import get_usage_summary

router = APIRouter()
billing_provider = BillingProvider()


@router.get("/plans", response_model=list[PlanResponse])
def plans(db: Session = Depends(get_db)):
    ensure_default_plans(db)
    return [serialize_plan(plan) for plan in db.query(Plan).filter(Plan.active.is_(True)).order_by(Plan.monthly_price_cents.asc()).all()]


@router.get("/organizations/{organization_id}/subscription", response_model=SubscriptionResponse)
def subscription(
    organization_id: int = Path(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    membership = require_org_role(db, current_user, organization_id, "member")
    return serialize_subscription(db, membership.organization)


@router.get("/organizations/{organization_id}/usage", response_model=UsageSummaryResponse)
def usage(
    organization_id: int = Path(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_org_role(db, current_user, organization_id, "member")
    summary = get_usage_summary(db, organization_id)
    summary["subscription_status"] = serialize_subscription(db, require_org_role(db, current_user, organization_id).organization)["status"]
    return summary


@router.post("/webhooks/{provider}")
async def billing_webhook(provider: str):
    return billing_provider.handle_webhook(provider)
