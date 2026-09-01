from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database.models import Organization, Plan, Subscription

DEFAULT_PLANS = {
    "free": {
        "name": "Free",
        "monthly_price_cents": 0,
        "limits": {
            "max_bots": 2,
            "max_documents": 20,
            "monthly_messages": 500,
            "storage_bytes": 50 * 1024 * 1024,
            "team_members": 2,
        },
    },
    "pro": {
        "name": "Pro",
        "monthly_price_cents": 2900,
        "limits": {
            "max_bots": 10,
            "max_documents": 500,
            "monthly_messages": 10000,
            "storage_bytes": 1024 * 1024 * 1024,
            "team_members": 5,
        },
    },
    "team": {
        "name": "Team",
        "monthly_price_cents": 9900,
        "limits": {
            "max_bots": 50,
            "max_documents": 5000,
            "monthly_messages": 100000,
            "storage_bytes": 10 * 1024 * 1024 * 1024,
            "team_members": 25,
        },
    },
}


def ensure_default_plans(db: Session) -> None:
    for code, payload in DEFAULT_PLANS.items():
        plan = db.query(Plan).filter(Plan.code == code).first()
        if not plan:
            db.add(
                Plan(
                    code=code,
                    name=payload["name"],
                    monthly_price_cents=payload["monthly_price_cents"],
                    limits_json=payload["limits"],
                )
            )
    db.commit()


def serialize_plan(plan: Plan) -> dict:
    return {
        "code": plan.code,
        "name": plan.name,
        "monthly_price_cents": plan.monthly_price_cents,
        "limits": plan.limits_json or {},
    }


def get_or_create_subscription(db: Session, organization_id: int) -> Subscription:
    subscription = db.query(Subscription).filter(Subscription.organization_id == organization_id).first()
    if subscription:
        return subscription
    plan = db.query(Plan).filter(Plan.code == "free").first()
    if not plan:
        ensure_default_plans(db)
        plan = db.query(Plan).filter(Plan.code == "free").first()
    if not plan:
        raise HTTPException(status_code=500, detail="Default billing plan is not configured")
    subscription = Subscription(
        organization_id=organization_id,
        plan_id=plan.id,
        status="active",
        current_period_start=datetime.utcnow(),
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


def get_plan_limits(db: Session, organization_id: int) -> dict[str, int]:
    subscription = get_or_create_subscription(db, organization_id)
    return subscription.plan.limits_json or {}


def serialize_subscription(db: Session, org: Organization) -> dict:
    subscription = get_or_create_subscription(db, org.id)
    return {
        "organization_id": org.id,
        "status": subscription.status,
        "plan": serialize_plan(subscription.plan),
    }


class BillingProvider:
    provider_name = "manual"

    def create_checkout_session(self, organization_id: int, plan_code: str) -> dict:
        return {"organization_id": organization_id, "plan_code": plan_code, "status": "not_configured"}

    def handle_webhook(self, provider: str) -> None:
        del provider
        raise HTTPException(status_code=404, detail="Billing webhook is not configured")
