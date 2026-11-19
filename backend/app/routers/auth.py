"""Accounts through Firebase Authentication.

`access_token` is a Firebase ID token (valid 1 hour); send it as `Authorization: Bearer <token>`.
Exchange `refresh_token` for a new one at POST /api/auth/refresh.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..config import get_settings
from ..db import get_db
from ..limits import limiter
from ..models import Role, User
from ..schemas import LoginIn, PasswordIn, ProfileIn, RegisterIn, TokenOut, user_out
from ..security import get_current_user
from ..services import accounts
from ..services.accounts import normalize_phone as _normalize_phone  # noqa: F401  (used by admin)
from ..services.tracking import utcnow
from ..store import Session

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=4096)


@router.post("/register", response_model=TokenOut, status_code=201)
@limiter.limit(get_settings().rate_limit_auth)
def register(request: Request, body: RegisterIn, db: Session = Depends(get_db)):
    """Create a passenger account with email or phone and a password (stored in Firebase Authentication)."""
    user = accounts.create_account(db, body.full_name, body.password, Role.passenger, email=body.email,
                                   phone=body.phone)
    _, tokens = accounts.sign_in(db, user.auth_email, body.password)
    return accounts.token_out(user, tokens)


@router.post("/login", response_model=TokenOut)
@limiter.limit(get_settings().rate_limit_auth)
def login(request: Request, body: LoginIn, db: Session = Depends(get_db)):
    """Log in with email or phone. Works for passengers, drivers and admins."""
    user, tokens = accounts.sign_in(db, body.identifier, body.password)
    if not user.is_active or (user.driver and not user.driver.is_active):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is deactivated")
    user.last_login_at = utcnow()
    db.commit()
    return accounts.token_out(user, tokens)


@router.post("/refresh", response_model=TokenOut)
@limiter.limit(get_settings().rate_limit_auth)
def refresh(request: Request, body: RefreshIn, db: Session = Depends(get_db)):
    """Exchange a refresh token for a new ID token."""
    tokens = accounts.refresh(body.refresh_token)
    from ..security import user_by_uid

    user = user_by_uid(tokens.uid)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Please log in again.")
    return accounts.token_out(user, tokens)


@router.post("/logout", status_code=204)
def logout(user: User = Depends(get_current_user)):
    """The client discards its tokens. Kept so apps have a single logout call."""
    return None


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.patch("/me")
def update_me(body: ProfileIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.full_name:
        user.full_name = body.full_name.strip()
    if body.phone:
        phone = accounts.normalize_phone(body.phone)
        other = accounts.find_user(phone=phone)
        if other and other.id != user.id:
            raise HTTPException(409, "Phone number already in use")
        user.phone = phone
    db.commit()
    return user_out(user)


@router.post("/me/password", status_code=204)
def change_password(body: PasswordIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        accounts.sign_in(db, user.auth_email, body.current_password)
    except HTTPException as exc:
        if exc.status_code == 401:
            raise HTTPException(400, "Current password is incorrect") from exc
        raise
    accounts.set_password(user, body.new_password)
