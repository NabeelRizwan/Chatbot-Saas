from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import User
from schemas.schemas import (
    InvitationCreateRequest,
    InvitationDecisionRequest,
    InvitationResponse,
    OrganizationCreateRequest,
    OrganizationMemberResponse,
    OrganizationMemberUpdateRequest,
    OrganizationResponse,
    OrganizationUpdateRequest,
)
from services.auth_service import get_current_user
from services.billing_service import get_or_create_subscription
from services.organization_service import (
    accept_invitation,
    create_invitation,
    create_organization,
    list_invitations,
    list_members,
    list_user_organizations,
    reject_invitation,
    update_member_role,
    update_organization,
)
from services.usage_service import ensure_can_add_member

router = APIRouter()


@router.get("/", response_model=list[OrganizationResponse])
def organizations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_user_organizations(db, current_user)


@router.post("/", response_model=OrganizationResponse)
def create_org(data: OrganizationCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    org = create_organization(db, current_user, data.name)
    get_or_create_subscription(db, org.id)
    return {"id": org.id, "name": org.name, "slug": org.slug, "role": "owner", "created_at": org.created_at}


@router.patch("/{organization_id}", response_model=OrganizationResponse)
def update_org(
    data: OrganizationUpdateRequest,
    organization_id: int = Path(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return update_organization(db, current_user, organization_id, data.name)


@router.get("/{organization_id}/members", response_model=list[OrganizationMemberResponse])
def members(
    organization_id: int = Path(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_members(db, current_user, organization_id)


@router.patch("/{organization_id}/members/{membership_id}", response_model=OrganizationMemberResponse)
def update_member(
    data: OrganizationMemberUpdateRequest,
    organization_id: int = Path(..., gt=0),
    membership_id: int = Path(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return update_member_role(db, current_user, organization_id, membership_id, data.role)


@router.get("/{organization_id}/invitations", response_model=list[InvitationResponse])
def invitations(
    organization_id: int = Path(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_invitations(db, current_user, organization_id)


@router.post("/{organization_id}/invitations", response_model=InvitationResponse)
def invite(
    data: InvitationCreateRequest,
    organization_id: int = Path(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_can_add_member(db, organization_id)
    return create_invitation(db, current_user, organization_id, data.email, data.role)


@router.post("/invitations/accept", response_model=InvitationResponse)
def accept_invite(data: InvitationDecisionRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return accept_invitation(db, current_user, data.token)


@router.post("/invitations/reject", response_model=InvitationResponse)
def reject_invite(data: InvitationDecisionRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return reject_invitation(db, current_user, data.token)
