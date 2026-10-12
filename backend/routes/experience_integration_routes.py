from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy.orm import Session

from database.connection import get_db
from database.experience_integration_models import ExperienceIntegration
from database.models import User
from schemas.experience_integrations import ExperienceIntegrations
from services.auth_service import get_current_user
from services.bot_service import get_bot_or_404, require_bot_organization
from services.public_access_service import enforce_public_origin
from services.experience_service import lock_settings_owner

router = APIRouter()


def load_integrations(db: Session, bot) -> ExperienceIntegrations:
    stored = db.query(ExperienceIntegration).filter_by(
        bot_id=bot.id, organization_id=bot.organization_id,
    ).first()
    return ExperienceIntegrations.model_validate(stored.config_json if stored else {})


@router.get("/bot/{bot_id}/experience/integrations", response_model=ExperienceIntegrations)
def get_integrations(bot_id: int = Path(..., gt=0),
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = get_bot_or_404(db, bot_id, user=user, minimum_role="viewer")
    return load_integrations(db, bot)


@router.put("/bot/{bot_id}/experience/integrations", response_model=ExperienceIntegrations)
def save_integrations(data: ExperienceIntegrations, bot_id: int = Path(..., gt=0),
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = get_bot_or_404(db, bot_id, user=user, minimum_role="editor")
    org_id = require_bot_organization(bot)
    lock_settings_owner(db, bot)
    stored = db.query(ExperienceIntegration).filter_by(bot_id=bot.id, organization_id=org_id).first()
    if stored is None:
        stored = ExperienceIntegration(bot_id=bot.id, organization_id=org_id)
        db.add(stored)
    stored.config_json = data.model_dump()
    db.commit()
    return data


@router.get("/public/widget/{bot_id}/experience/integrations", response_model=ExperienceIntegrations)
def public_integrations(request: Request, bot_id: int = Path(..., gt=0), db: Session = Depends(get_db)):
    from routes.public_routes import get_public_bot_or_404
    from database.experience_models import ExperienceSettings

    bot = get_public_bot_or_404(db, bot_id)
    enforce_public_origin(bot, request)
    settings = db.query(ExperienceSettings).filter_by(bot_id=bot.id, organization_id=bot.organization_id).first()
    if not settings or not settings.enabled:
        return ExperienceIntegrations()
    configured = load_integrations(db, bot)
    return ExperienceIntegrations(
        booking=configured.booking if configured.booking.enabled else {},
        orders=configured.orders if configured.orders.enabled else {},
    )
