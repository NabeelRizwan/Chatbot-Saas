import hashlib
import re
import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database.models import Organization, OrganizationInvitation, OrganizationMembership, User

ROLE_ORDER = {"viewer": 1, "editor": 2, "member": 3, "admin": 4, "owner": 5}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or f"org-{secrets.token_hex(3)}"


def unique_slug(db: Session, name: str, exclude_organization_id: int | None = None) -> str:
    base = slugify(name)
    slug = base
    suffix = 1
    query = db.query(Organization).filter(Organization.slug == slug)
    if exclude_organization_id:
        query = query.filter(Organization.id != exclude_organization_id)
    while query.first():
        suffix += 1
        slug = f"{base}-{suffix}"
        query = db.query(Organization).filter(Organization.slug == slug)
        if exclude_organization_id:
            query = query.filter(Organization.id != exclude_organization_id)
    return slug


def serialize_org(org: Organization, role: str) -> dict:
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "role": role,
        "created_at": org.created_at,
    }


def create_organization(db: Session, user: User, name: str) -> Organization:
    org = Organization(name=name, slug=unique_slug(db, name), owner_user_id=user.id)
    db.add(org)
    db.flush()
    db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner"))
    db.commit()
    db.refresh(org)
    return org


def update_organization(db: Session, user: User, organization_id: int, name: str) -> dict:
    membership = require_org_role(db, user, organization_id, "admin")
    org = membership.organization
    org.name = name.strip()
    org.slug = unique_slug(db, org.name, exclude_organization_id=org.id)
    db.commit()
    db.refresh(org)
    return serialize_org(org, membership.role)


def list_user_organizations(db: Session, user: User) -> list[dict]:
    memberships = (
        db.query(OrganizationMembership)
        .join(Organization, Organization.id == OrganizationMembership.organization_id)
        .filter(OrganizationMembership.user_id == user.id)
        .order_by(Organization.created_at.asc())
        .all()
    )
    return [serialize_org(membership.organization, membership.role) for membership in memberships]


def get_membership(db: Session, user: User, organization_id: int) -> OrganizationMembership | None:
    return (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.organization_id == organization_id)
        .filter(OrganizationMembership.user_id == user.id)
        .first()
    )


def require_org_role(db: Session, user: User, organization_id: int, minimum_role: str = "member") -> OrganizationMembership:
    membership = get_membership(db, user, organization_id)
    if not membership:
        raise HTTPException(status_code=404, detail="Organization not found")
    if ROLE_ORDER[membership.role] < ROLE_ORDER[minimum_role]:
        raise HTTPException(status_code=403, detail="You do not have permission for this organization")
    return membership


def role_can_manage_actor(actor_role: str, target_role: str) -> bool:
    if actor_role == "owner":
        return True
    if actor_role == "admin":
        return target_role in ("member", "editor", "viewer")
    return False


def list_members(db: Session, user: User, organization_id: int) -> list[dict]:
    require_org_role(db, user, organization_id, "member")
    memberships = (
        db.query(OrganizationMembership)
        .join(User, User.id == OrganizationMembership.user_id)
        .filter(OrganizationMembership.organization_id == organization_id)
        .order_by(OrganizationMembership.created_at.asc())
        .all()
    )
    return [
        {
            "id": membership.id,
            "user_id": membership.user.id,
            "name": membership.user.name,
            "email": membership.user.email,
            "role": membership.role,
            "created_at": membership.created_at,
        }
        for membership in memberships
    ]


def update_member_role(db: Session, user: User, organization_id: int, membership_id: int, role: str) -> dict:
    actor = require_org_role(db, user, organization_id, "admin")
    target = (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.organization_id == organization_id)
        .filter(OrganizationMembership.id == membership_id)
        .first()
    )
    if not target:
        raise HTTPException(status_code=404, detail="Team member not found")
    if target.role == "owner":
        raise HTTPException(status_code=403, detail="Owner role cannot be changed")
    if not role_can_manage_actor(actor.role, target.role) or not role_can_manage_actor(actor.role, role):
        raise HTTPException(status_code=403, detail="You cannot manage that role")
    target.role = role
    db.commit()
    db.refresh(target)
    return {
        "id": target.id,
        "user_id": target.user.id,
        "name": target.user.name,
        "email": target.user.email,
        "role": target.role,
        "created_at": target.created_at,
    }


def _hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_invitation(db: Session, user: User, organization_id: int, email: str, role: str) -> dict:
    actor = require_org_role(db, user, organization_id, "admin")
    if not role_can_manage_actor(actor.role, role):
        raise HTTPException(status_code=403, detail="You cannot invite that role")
    normalized_email = email.strip().lower()
    existing_member = (
        db.query(OrganizationMembership)
        .join(User, User.id == OrganizationMembership.user_id)
        .filter(OrganizationMembership.organization_id == organization_id)
        .filter(User.email == normalized_email)
        .first()
    )
    if existing_member:
        raise HTTPException(status_code=409, detail="That user is already a member")
    existing_invite = (
        db.query(OrganizationInvitation)
        .filter(OrganizationInvitation.organization_id == organization_id)
        .filter(OrganizationInvitation.email == normalized_email)
        .filter(OrganizationInvitation.status == "pending")
        .filter(OrganizationInvitation.expires_at > datetime.utcnow())
        .first()
    )
    if existing_invite:
        raise HTTPException(status_code=409, detail="A pending invitation already exists")
    token = secrets.token_urlsafe(36)
    invite = OrganizationInvitation(
        organization_id=organization_id,
        email=normalized_email,
        role=role,
        token_hash=_hash_invite_token(token),
        invited_by_user_id=user.id,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return serialize_invite(invite, invite_token=token)


def serialize_invite(invite: OrganizationInvitation, invite_token: str | None = None) -> dict:
    return {
        "id": invite.id,
        "organization_id": invite.organization_id,
        "email": invite.email,
        "role": invite.role,
        "status": invite.status,
        "expires_at": invite.expires_at,
        "invite_token": invite_token,
    }


def list_invitations(db: Session, user: User, organization_id: int) -> list[dict]:
    require_org_role(db, user, organization_id, "admin")
    invites = (
        db.query(OrganizationInvitation)
        .filter(OrganizationInvitation.organization_id == organization_id)
        .order_by(OrganizationInvitation.created_at.desc())
        .all()
    )
    return [serialize_invite(invite) for invite in invites]


def accept_invitation(db: Session, user: User, token: str) -> dict:
    invite = db.query(OrganizationInvitation).filter(OrganizationInvitation.token_hash == _hash_invite_token(token)).first()
    if not invite or invite.status != "pending" or invite.expires_at < datetime.utcnow():
        raise HTTPException(status_code=404, detail="Invitation is invalid or expired")
    if invite.email.lower() != user.email.lower():
        raise HTTPException(status_code=403, detail="Invitation was sent to a different email")
    if not get_membership(db, user, invite.organization_id):
        db.add(OrganizationMembership(organization_id=invite.organization_id, user_id=user.id, role=invite.role))
    invite.status = "accepted"
    invite.responded_at = datetime.utcnow()
    db.commit()
    return serialize_invite(invite)


def reject_invitation(db: Session, user: User, token: str) -> dict:
    invite = db.query(OrganizationInvitation).filter(OrganizationInvitation.token_hash == _hash_invite_token(token)).first()
    if not invite or invite.status != "pending" or invite.expires_at < datetime.utcnow():
        raise HTTPException(status_code=404, detail="Invitation is invalid or expired")
    if invite.email.lower() != user.email.lower():
        raise HTTPException(status_code=403, detail="Invitation was sent to a different email")
    invite.status = "rejected"
    invite.responded_at = datetime.utcnow()
    db.commit()
    return serialize_invite(invite)
