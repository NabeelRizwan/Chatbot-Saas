"""Optional experience features around the existing answer pipeline."""
import hashlib
import json
import unicodedata
from datetime import datetime, timedelta
from time import perf_counter
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from database.experience_models import (
    ApprovedFaq, ExperienceLead, ExperienceProduct, ExperienceSettings, FaqAlias,
    LeadSubmission, SavedTestCase, SavedTestResult, SavedTestRun,
)
from database.models import Bot, Document
from schemas.experience import ExperienceSettingsInput


def normalize_question(value):
    # Preserve punctuation, quantities and negations; approved aliases are explicit.
    return " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())


def scoped(db, model, bot):
    return db.query(model).filter(model.bot_id == bot.id, model.organization_id == bot.organization_id)


def record_or_404(db, model, bot, record_id):
    row = scoped(db, model, bot).filter(model.id == record_id).first()
    if row is None:
        raise HTTPException(404, "Record not found")
    return row


def _dump(row, fields):
    return {field: getattr(row, field) for field in fields.split()}


def get_settings(db, bot):
    row = scoped(db, ExperienceSettings, bot).first()
    defaults = ExperienceSettingsInput().model_dump()
    if row:
        defaults.update({key: getattr(row, key) for key in defaults})
    return defaults


def lock_settings_owner(db, bot):
    owner = db.query(Bot).filter(Bot.id == bot.id, Bot.organization_id == bot.organization_id).with_for_update().first()
    if owner is None:
        raise HTTPException(404, "Bot not found")


def save_settings(db, bot, data):
    lock_settings_owner(db, bot)
    row = scoped(db, ExperienceSettings, bot).first()
    if row is None:
        row = ExperienceSettings(bot_id=bot.id, organization_id=bot.organization_id)
        db.add(row)
    for field, value in data.model_dump().items():
        setattr(row, field, value)
    db.commit()
    return get_settings(db, bot)


def source_document(db, bot, document_id, *, required=False):
    from services.native_rag.knowledge import ready_documents
    row = ready_documents(db, bot).filter(Document.id == document_id).first() if document_id else None
    if required and row is None:
        raise HTTPException(422, "Choose a ready, active knowledge source belonging to this bot")
    return row


def fingerprint(document):
    content = document.source_content_hash or document.content_hash or hashlib.sha256((document.raw_text or "").encode()).hexdigest()
    return hashlib.sha256(f"{document.id}:{document.version}:{content}".encode()).hexdigest()


def source_status(db, bot, row):
    if not row.source_document_id:
        return "unbound"
    document = source_document(db, bot, row.source_document_id)
    if not document or document.status in {"deleted", "deleting", "failed"}:
        return "missing"
    return "current" if row.source_fingerprint == fingerprint(document) else "changed"


def serialize_faq(db, bot, row):
    value = _dump(row, "id question answer aliases source_document_id source_url approved enabled created_at updated_at")
    value["source_status"] = source_status(db, bot, row)
    return value


def save_faq(db, bot, data, actor_id, faq_id=None):
    row = record_or_404(db, ApprovedFaq, bot, faq_id) if faq_id else ApprovedFaq(bot_id=bot.id, organization_id=bot.organization_id)
    doc = source_document(db, bot, data.source_document_id, required=bool(data.source_document_id))
    aliases = list(dict.fromkeys(normalize_question(q) for q in [data.question, *data.aliases]))
    if any(not q or len(q) > 1000 for q in aliases):
        raise HTTPException(422, "An approved question is too long after normalization")
    for field, value in data.model_dump().items():
        setattr(row, field, value)
    row.source_fingerprint = fingerprint(doc) if doc else None
    row.source_url = data.source_url or (doc.source_url if doc else None)
    row.approved_by_user_id = actor_id if data.approved else None
    try:
        if not faq_id:
            db.add(row)
        db.flush()
        db.query(FaqAlias).filter(FaqAlias.faq_id == row.id, FaqAlias.bot_id == bot.id).delete(synchronize_session=False)
        for question in aliases:
            db.add(FaqAlias(bot_id=bot.id, faq_id=row.id, normalized_question=question,
                question_hash=hashlib.sha256(question.encode()).hexdigest()))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This question or alias is already assigned to another FAQ") from exc
    return serialize_faq(db, bot, row)


def delete_faq(db, bot, faq_id):
    row = record_or_404(db, ApprovedFaq, bot, faq_id)
    db.query(FaqAlias).filter(FaqAlias.faq_id == row.id, FaqAlias.bot_id == bot.id).delete(synchronize_session=False)
    db.delete(row)
    db.commit()


def lookup_approved_faq(db, bot, question, history=None):
    settings = get_settings(db, bot)
    if not settings["enabled"] or not settings["approved_faq_enabled"]:
        return None
    normalized = normalize_question(question)
    row = scoped(db, ApprovedFaq, bot).join(FaqAlias, FaqAlias.faq_id == ApprovedFaq.id).filter(
        FaqAlias.bot_id == bot.id, FaqAlias.question_hash == hashlib.sha256(normalized.encode()).hexdigest(),
        FaqAlias.normalized_question == normalized,
        ApprovedFaq.approved.is_(True), ApprovedFaq.enabled.is_(True),
    ).first()
    if not row or source_status(db, bot, row) in {"changed", "missing"}:
        return None
    sources = []
    if row.source_url:
        sources = [{"document_id": row.source_document_id, "title": row.question,
                    "source_url": row.source_url, "source_type": "approved_faq"}]
    return {"reply": row.answer, "sources": sources, "retrieved_chunks": [], "faq_id": row.id}


def serialize_product(db, bot, row):
    result = _dump(row, "id title description url image_url price_amount currency source_document_id enabled created_at updated_at")
    result["source_status"] = source_status(db, bot, row)
    return result


def save_product(db, bot, data, product_id=None):
    row = record_or_404(db, ExperienceProduct, bot, product_id) if product_id else ExperienceProduct(bot_id=bot.id, organization_id=bot.organization_id)
    doc = source_document(db, bot, data.source_document_id, required=bool(data.source_document_id))
    for field, value in data.model_dump().items():
        setattr(row, field, value)
    row.source_fingerprint = fingerprint(doc) if doc else None
    if not product_id:
        db.add(row)
    db.commit()
    return serialize_product(db, bot, row)


def select_product_cards(db, bot, sources):
    settings = get_settings(db, bot)
    if not settings["enabled"] or not settings["product_cards_enabled"]:
        return []
    ids = {int(s["document_id"]) for s in sources if isinstance(s, dict) and str(s.get("document_id", "")).isdigit()}
    urls = {str(s.get("source_url") or "").split("#", 1)[0].rstrip("/") for s in sources if isinstance(s, dict)} - {""}
    if not ids and not urls:
        return []
    # Narrow by source in SQL instead of scanning every catalog item after each reply.
    variants = urls | {url + "/" for url in urls}
    from services.native_rag.knowledge import ready_documents
    documents = ready_documents(db, bot).filter(or_(Document.id.in_(ids), Document.source_url.in_(variants), Document.canonical_url.in_(variants))).all()
    by_id = {doc.id: doc for doc in documents}
    rows = scoped(db, ExperienceProduct, bot).filter(ExperienceProduct.enabled.is_(True), or_(
        ExperienceProduct.source_document_id.in_(set(by_id)),
        ExperienceProduct.source_document_id.is_(None) & ExperienceProduct.url.in_(variants),
    )).order_by(ExperienceProduct.id).limit(20).all()
    cards = []
    for row in rows:
        doc = by_id.get(row.source_document_id)
        if row.source_document_id and (not doc or doc.status in {"deleted", "deleting", "failed"} or row.source_fingerprint != fingerprint(doc)):
            continue
        cards.append(_dump(row, "id title description url image_url price_amount currency"))
        if len(cards) == 4:
            break
    return cards


def capture_lead(db, bot, data):
    settings = get_settings(db, bot)
    if not settings["enabled"] or not settings["lead_form_enabled"]:
        raise HTTPException(404, "Contact form is not enabled")
    payload = data.model_dump(exclude={"session_token", "idempotency_key"})
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    for attempt in range(2):
        previous = db.query(LeadSubmission).filter(
            LeadSubmission.bot_id == bot.id, LeadSubmission.session_id == data.session_id,
            LeadSubmission.idempotency_key == data.idempotency_key,
        ).first()
        if previous:
            if previous.payload_hash != digest:
                raise HTTPException(409, "This submission ID was already used. Please submit again.")
            return {"received": True}
        email_normalized = data.email.casefold()
        lead = scoped(db, ExperienceLead, bot).filter(ExperienceLead.email_normalized == email_normalized).first()
        try:
            if lead is None:
                lead = ExperienceLead(bot_id=bot.id, organization_id=bot.organization_id,
                    email=data.email, email_normalized=email_normalized, name=data.name,
                    phone=data.phone, message=data.message)
                db.add(lead)
                db.flush()
            db.add(LeadSubmission(lead_id=lead.id, bot_id=bot.id, session_id=data.session_id,
                idempotency_key=data.idempotency_key, payload_hash=digest, name=data.name,
                phone=data.phone, message=data.message, consent_text=settings["lead_consent_text"]))
            db.commit()
            return {"received": True}
        except IntegrityError:
            db.rollback()
            if attempt:
                raise HTTPException(409, "Please retry this contact submission")


def serialize_lead(row):
    return _dump(row, "id name email phone message status consent_at created_at")


def serialize_case(row):
    return _dump(row, "id question expected_answer required_phrases forbidden_phrases enabled created_at updated_at")


def save_case(db, bot, data, case_id=None):
    row = record_or_404(db, SavedTestCase, bot, case_id) if case_id else SavedTestCase(bot_id=bot.id, organization_id=bot.organization_id)
    for field, value in data.model_dump().items():
        setattr(row, field, value)
    if not case_id:
        db.add(row)
    db.commit()
    return serialize_case(row)


def serialize_run(db, row):
    result = _dump(row, "id status provider model created_at completed_at")
    result["results"] = [_dump(item, "id case_id question expected_answer answer latency_ms status missing_phrases forbidden_matches error sources")
        for item in db.query(SavedTestResult).filter(SavedTestResult.run_id == row.id).order_by(SavedTestResult.position).all()]
    return result


def create_test_run(db, bot, data, actor_id):
    cases = scoped(db, SavedTestCase, bot).filter(SavedTestCase.id.in_(data.case_ids), SavedTestCase.enabled.is_(True)).all()
    by_id = {case.id: case for case in cases}
    if len(by_id) != len(data.case_ids):
        raise HTTPException(422, "Choose enabled saved questions from this bot")
    # Serialize run creation by bot so one dashboard cannot start an unbounded backlog.
    db.query(Bot).filter(Bot.id == bot.id).with_for_update().first()
    if scoped(db, SavedTestRun, bot).filter(SavedTestRun.status.in_(["pending", "running"])).first():
        raise HTTPException(409, "Resume the existing unfinished test run first")
    row = SavedTestRun(bot_id=bot.id, organization_id=bot.organization_id, created_by_user_id=actor_id,
        provider=bot.provider, model=bot.model_name)
    db.add(row)
    db.flush()
    for index, case_id in enumerate(data.case_ids):
        case = by_id[case_id]
        db.add(SavedTestResult(run_id=row.id, case_id=case.id, position=index, question=case.question,
            expected_answer=case.expected_answer, required_phrases=case.required_phrases,
            forbidden_phrases=case.forbidden_phrases))
    db.commit()
    return serialize_run(db, row)


def score_phrases(answer, required, forbidden):
    normalized = normalize_question(answer)
    missing = [phrase for phrase in required if normalize_question(phrase) not in normalized]
    found = [phrase for phrase in forbidden if normalize_question(phrase) in normalized]
    status = "needs_review" if missing or found else "passed_checks" if required or forbidden else "manual_review"
    return status, missing, found


def execute_next_case(db, bot, run_id):
    from services.observability_service import ChatTrace
    from services.rag_service import answer_question
    from services.usage_service import consume_message_quota, ensure_can_send_message, release_message_quota

    run = record_or_404(db, SavedTestRun, bot, run_id)
    if run.status == "completed":
        return serialize_run(db, run)
    if run.provider != bot.provider or run.model != bot.model_name:
        raise HTTPException(409, "The bot model changed. Cancel this run and create a new one.")
    now, token = datetime.utcnow(), uuid4().hex
    claimed = scoped(db, SavedTestRun, bot).filter(SavedTestRun.id == run_id,
        SavedTestRun.status != "completed", or_(SavedTestRun.lease_expires_at.is_(None), SavedTestRun.lease_expires_at < now)
    ).update({"lease_token": token, "lease_expires_at": now + timedelta(minutes=10), "status": "running"}, synchronize_session=False)
    db.commit()
    if not claimed:
        raise HTTPException(409, "A saved question is already being tested. Wait for it to finish.")
    # A lost worker cannot be retried silently: the provider may already have charged it.
    stale = db.query(SavedTestResult).filter(SavedTestResult.run_id == run_id, SavedTestResult.status == "running").all()
    for previous in stale:
        previous.status = "error"
        previous.error = "Interrupted test. Start a new run to retry this question."
    result = db.query(SavedTestResult).filter(SavedTestResult.run_id == run_id, SavedTestResult.status == "pending").order_by(SavedTestResult.position).first()
    if not result:
        run = record_or_404(db, SavedTestRun, bot, run_id)
        run.status, run.completed_at, run.lease_token, run.lease_expires_at = "completed", now, None, None
        db.commit()
        return serialize_run(db, run)
    result.status = "running"
    result_id, question = result.id, result.question
    db.commit()
    started, usage_key = perf_counter(), None
    answer, sources, error = None, [], None
    try:
        usage_key = ensure_can_send_message(db, bot.organization_id,
            idempotency_key=f"saved-test:{run_id}:{result_id}", channel="saved_test")
        answer, sources, _ = answer_question(db=db, bot=bot, question=question, history=[],
            session_id=f"saved-test:{run_id}:{result_id}", trace=ChatTrace(bot_id=bot.id, channel="saved_test"))
        consume_message_quota(db, bot.organization_id, usage_key)
    except Exception as exc:
        db.rollback()
        if usage_key:
            release_message_quota(db, bot.organization_id, usage_key)
        # Avoid leaking provider credentials or raw upstream request bodies in test reports.
        code = getattr(exc, "status_code", None)
        error = f"Answer request failed{f' (HTTP {code})' if code else ''}. Check service diagnostics; retry in a new run."
    latency = round((perf_counter() - started) * 1000)
    db.expire_all()
    run = record_or_404(db, SavedTestRun, bot, run_id)
    if run.lease_token != token:
        raise HTTPException(409, "The test lease expired. Reload this run.")
    result = db.query(SavedTestResult).filter(SavedTestResult.id == result_id, SavedTestResult.run_id == run_id).one()
    result.answer, result.sources, result.latency_ms, result.error = answer, json.loads(json.dumps(sources, default=str)), latency, error
    if error:
        result.status = "error"
    else:
        result.status, result.missing_phrases, result.forbidden_matches = score_phrases(answer, result.required_phrases, result.forbidden_phrases)
    db.flush()
    pending = db.query(SavedTestResult).filter(SavedTestResult.run_id == run_id, SavedTestResult.status == "pending").first()
    run.lease_token, run.lease_expires_at = None, None
    if not pending:
        run.status, run.completed_at = "completed", datetime.utcnow()
    db.commit()
    return serialize_run(db, run)


def cancel_run(db, bot, run_id):
    run = record_or_404(db, SavedTestRun, bot, run_id)
    if run.lease_expires_at and run.lease_expires_at > datetime.utcnow():
        raise HTTPException(409, "Wait for the current question to finish before cancelling")
    db.query(SavedTestResult).filter(SavedTestResult.run_id == run.id,
        SavedTestResult.status.in_(["pending", "running"])).update({"status": "error", "error": "Cancelled by the operator"}, synchronize_session=False)
    run.status, run.completed_at, run.lease_token, run.lease_expires_at = "completed", datetime.utcnow(), None, None
    db.commit()
    return serialize_run(db, run)
