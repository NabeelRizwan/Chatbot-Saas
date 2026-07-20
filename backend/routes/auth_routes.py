from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import User, AuthRefreshSession, Customer
from schemas.schemas import AuthLoginRequest, AuthLogoutRequest, AuthRefreshRequest, AuthRegisterRequest, AuthTokenResponse, UserResponse, UserUpdateRequest, ChangePasswordRequest
import secrets
from services.auth_service import create_access_token, get_current_user, hash_password, revoke_refresh_token, rotate_refresh_session, token_response, verify_password
from services.billing_service import get_or_create_subscription
from services.organization_service import create_organization

router = APIRouter()


@router.get("/profile", response_model=UserResponse)
def profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not current_user.customer_id:
        api_key = secrets.token_hex(16)
        customer = Customer(name=current_user.name, api_key=api_key)
        db.add(customer)
        db.flush()
        current_user.customer_id = customer.id
        db.commit()
    return current_user


@router.patch("/profile", response_model=UserResponse)
def update_profile(data: UserUpdateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if data.name is not None:
        current_user.name = data.name.strip()
    if data.bio is not None:
        current_user.bio = data.bio.strip()
    if data.avatar_url is not None:
        current_user.avatar_url = data.avatar_url.strip()
    if data.preferences is not None:
        current_user.preferences = data.preferences
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/change-password")
def change_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not verify_password(data.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect old password")
    
    current_user.password_hash = hash_password(data.new_password)
    db.commit()
    return {"success": True}


@router.get("/sessions")
def list_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    sessions = db.query(AuthRefreshSession).filter(
        AuthRefreshSession.user_id == current_user.id,
        AuthRefreshSession.revoked_at == None
    ).order_by(AuthRefreshSession.created_at.desc()).all()
    
    return [
        {
            "id": s.id,
            "created_at": s.created_at,
            "expires_at": s.expires_at,
        }
        for s in sessions
    ]


@router.delete("/sessions/{session_id}")
def revoke_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    session = db.query(AuthRefreshSession).filter(
        AuthRefreshSession.id == session_id,
        AuthRefreshSession.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    session.revoked_at = datetime.utcnow()
    db.commit()
    return {"success": True}


@router.post("/register", response_model=AuthTokenResponse)
def register(data: AuthRegisterRequest, db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    
    api_key = secrets.token_hex(16)
    customer = Customer(name=data.name.strip(), api_key=api_key)
    db.add(customer)
    db.flush()

    is_first_user = db.query(User).count() == 0
    user = User(
        name=data.name.strip(),
        email=email,
        password_hash=hash_password(data.password),
        customer_id=customer.id,
        is_admin=is_first_user
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    org = create_organization(db, user, data.organization_name or f"{user.name}'s Workspace")
    get_or_create_subscription(db, org.id)
    return token_response(db, user)


@router.post("/login", response_model=AuthTokenResponse)
def login(data: AuthLoginRequest, db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    user = db.query(User).filter(User.email == email, User.disabled.is_(False)).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return token_response(db, user)


@router.post("/refresh", response_model=AuthTokenResponse)
def refresh(data: AuthRefreshRequest, db: Session = Depends(get_db)):
    user, next_refresh = rotate_refresh_session(db, data.refresh_token)
    access_token, expires_in = create_access_token(user)
    return {
        "access_token": access_token,
        "refresh_token": next_refresh,
        "expires_in": expires_in,
        "user": {"id": user.id, "name": user.name, "email": user.email},
    }


@router.post("/logout")
def logout(data: AuthLogoutRequest, db: Session = Depends(get_db)):
    revoke_refresh_token(db, data.refresh_token)
    return {"success": True}
