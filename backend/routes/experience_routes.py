from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from database.connection import get_db
from database.experience_models import ApprovedFaq, ExperienceLead, ExperienceProduct, LeadSubmission, SavedTestCase, SavedTestRun
from database.models import ConversationMessage, User
from schemas.experience import ExperienceSettingsInput, FaqInput, LeadInput, LeadUpdate, ProductInput, ProductTurnInput, TestCaseInput, TestRunInput
from services.auth_service import get_current_user
from services.bot_service import get_bot_or_404
from services.public_access_service import enforce_public_origin, validate_public_session
from services import experience_service as service
from utils.rate_limiter import enforce_rate_limit

router = APIRouter(prefix="/bot/{bot_id}/experience", tags=["Customer experience"])
public_router = APIRouter(prefix="/public/widget/{bot_id}/experience", tags=["Widget experience"])


def _bot(db, bot_id, user, role="viewer"):
    return get_bot_or_404(db, bot_id, user=user, minimum_role=role)


def _public_bot(db, bot_id, request):
    from routes.public_routes import get_public_bot_or_404
    bot = get_public_bot_or_404(db, bot_id)
    enforce_public_origin(bot, request)
    if not bot.organization_id:
        raise HTTPException(404, "Bot not found")
    return bot


@router.get("")
@router.get("/", include_in_schema=False)
def settings(bot_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.get_settings(db, _bot(db, bot_id, user))


@router.put("/settings")
def update_settings(bot_id: int, data: ExperienceSettingsInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.save_settings(db, _bot(db, bot_id, user, "editor"), data)


@router.get("/faqs")
def faqs(bot_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = _bot(db, bot_id, user)
    return {"items": [service.serialize_faq(db, bot, row) for row in service.scoped(db, ApprovedFaq, bot).order_by(ApprovedFaq.id.desc()).limit(500).all()]}


@router.post("/faqs", status_code=201)
def create_faq(bot_id: int, data: FaqInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = _bot(db, bot_id, user, "editor")
    if service.scoped(db, ApprovedFaq, bot).count() >= 500:
        raise HTTPException(409, "This bot already has 500 FAQs")
    return service.save_faq(db, bot, data, user.id)


@router.put("/faqs/{faq_id}")
def update_faq(bot_id: int, faq_id: int, data: FaqInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.save_faq(db, _bot(db, bot_id, user, "editor"), data, user.id, faq_id)


@router.delete("/faqs/{faq_id}", status_code=204)
def delete_faq(bot_id: int, faq_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service.delete_faq(db, _bot(db, bot_id, user, "editor"), faq_id)
    return Response(status_code=204)


@router.get("/products")
def products(bot_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = _bot(db, bot_id, user)
    return {"items": [service.serialize_product(db, bot, row) for row in service.scoped(db, ExperienceProduct, bot).order_by(ExperienceProduct.id.desc()).limit(500).all()]}


@router.post("/products", status_code=201)
def create_product(bot_id: int, data: ProductInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = _bot(db, bot_id, user, "editor")
    if service.scoped(db, ExperienceProduct, bot).count() >= 500:
        raise HTTPException(409, "This bot already has 500 products")
    return service.save_product(db, bot, data)


@router.put("/products/{product_id}")
def update_product(bot_id: int, product_id: int, data: ProductInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.save_product(db, _bot(db, bot_id, user, "editor"), data, product_id)


@router.delete("/products/{product_id}", status_code=204)
def delete_product(bot_id: int, product_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = _bot(db, bot_id, user, "editor")
    db.delete(service.record_or_404(db, ExperienceProduct, bot, product_id))
    db.commit()
    return Response(status_code=204)


@router.get("/leads")
def leads(bot_id: int, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = _bot(db, bot_id, user, "member")
    query = service.scoped(db, ExperienceLead, bot)
    return {"total": query.count(), "items": [service.serialize_lead(row) for row in query.order_by(ExperienceLead.id.desc()).offset(offset).limit(limit).all()]}


@router.get("/leads/{lead_id}")
def lead_detail(bot_id: int, lead_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = _bot(db, bot_id, user, "member")
    row = service.record_or_404(db, ExperienceLead, bot, lead_id)
    result = service.serialize_lead(row)
    result["submissions"] = [service._dump(item, "id name phone message consent_text consent_at") for item in db.query(LeadSubmission).filter(
        LeadSubmission.bot_id == bot.id, LeadSubmission.lead_id == row.id).order_by(LeadSubmission.id.desc()).limit(100).all()]
    return result


@router.patch("/leads/{lead_id}")
def update_lead(bot_id: int, lead_id: int, data: LeadUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = _bot(db, bot_id, user, "editor")
    row = service.record_or_404(db, ExperienceLead, bot, lead_id)
    row.status = data.status
    db.commit()
    return service.serialize_lead(row)


@router.delete("/leads/{lead_id}", status_code=204)
def delete_lead(bot_id: int, lead_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = _bot(db, bot_id, user, "editor")
    row = service.record_or_404(db, ExperienceLead, bot, lead_id)
    db.query(LeadSubmission).filter(LeadSubmission.bot_id == bot.id, LeadSubmission.lead_id == row.id).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@router.get("/test-cases")
def test_cases(bot_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = _bot(db, bot_id, user)
    return {"items": [service.serialize_case(row) for row in service.scoped(db, SavedTestCase, bot).order_by(SavedTestCase.id.desc()).limit(500).all()]}


@router.post("/test-cases", status_code=201)
def create_test_case(bot_id: int, data: TestCaseInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = _bot(db, bot_id, user, "editor")
    if service.scoped(db, SavedTestCase, bot).count() >= 500:
        raise HTTPException(409, "This bot already has 500 saved questions")
    return service.save_case(db, bot, data)


@router.put("/test-cases/{case_id}")
def update_test_case(bot_id: int, case_id: int, data: TestCaseInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.save_case(db, _bot(db, bot_id, user, "editor"), data, case_id)


@router.delete("/test-cases/{case_id}", status_code=204)
def delete_test_case(bot_id: int, case_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = _bot(db, bot_id, user, "editor")
    db.delete(service.record_or_404(db, SavedTestCase, bot, case_id))
    db.commit()
    return Response(status_code=204)


@router.get("/test-runs")
def test_runs(bot_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = _bot(db, bot_id, user)
    return {"items": [service.serialize_run(db, row) for row in service.scoped(db, SavedTestRun, bot).order_by(SavedTestRun.id.desc()).limit(30).all()]}


@router.get("/test-runs/{run_id}")
def test_run(bot_id: int, run_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = _bot(db, bot_id, user)
    run = service.record_or_404(db, SavedTestRun, bot, run_id)
    from services.chat_execution.saved_tests import refresh_run
    refresh_run(db, bot, run)
    return service.serialize_run(db, run)


@router.post("/test-runs", status_code=201)
def create_test_run(bot_id: int, data: TestRunInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.create_test_run(db, _bot(db, bot_id, user, "editor"), data, user.id)


@router.post("/test-runs/{run_id}/execute-next")
def execute_test_run(bot_id: int, run_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bot = _bot(db, bot_id, user, "editor")
    enforce_rate_limit(scope="auth_chat", org_id=bot.organization_id, bot_id=bot.id, client_id=f"tests-{user.id}")
    return service.execute_next_case(db, bot, run_id)


@router.post("/test-runs/{run_id}/cancel")
def cancel_test_run(bot_id: int, run_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.cancel_run(db, _bot(db, bot_id, user, "editor"), run_id)


@public_router.get("")
@public_router.get("/", include_in_schema=False)
def public_settings(bot_id: int, request: Request, db: Session = Depends(get_db)):
    return service.get_settings(db, _public_bot(db, bot_id, request))


@public_router.post("/leads", status_code=201)
def public_lead(bot_id: int, data: LeadInput, request: Request, db: Session = Depends(get_db)):
    bot = _public_bot(db, bot_id, request)
    validate_public_session(db, bot, data.session_id, data.session_token)
    for identity in (f"session-{data.session_id}", f"ip-{request.client.host if request.client else 'unknown'}", "bot-wide"):
        enforce_rate_limit(scope="public_chat", org_id=bot.organization_id, bot_id=bot.id, client_id=f"leads-{identity}")
    return service.capture_lead(db, bot, data)


@public_router.post("/products/for-turn")
def public_products_for_turn(bot_id: int, data: ProductTurnInput, request: Request, db: Session = Depends(get_db)):
    bot = _public_bot(db, bot_id, request)
    validate_public_session(db, bot, data.session_id, data.session_token)
    message = db.query(ConversationMessage).filter(
        ConversationMessage.bot_id == bot.id, ConversationMessage.organization_id == bot.organization_id,
        ConversationMessage.session_id == data.session_id, ConversationMessage.client_turn_id == data.turn_id,
        ConversationMessage.status == "success",
    ).first()
    sources = (message.token_usage or {}).get("experience_sources", []) if message else []
    return {"products": service.select_product_cards(db, bot, sources if isinstance(sources, list) else []), "pending": message is None}
