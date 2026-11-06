from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..limits import limiter
from ..models import DEFAULT_PREFS, Role, User
from ..schemas import LoginIn, PasswordIn, ProfileIn, RegisterIn, TokenOut, user_out
from ..security import create_token, get_current_user, hash_password, verify_password
from ..services.tracking import utcnow

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _normalize_phone(p: str | None) -> str | None:
    if not p:
        return None
    p = p.replace(" ", "").replace("-", "")
    if p.startswith("03") and len(p) == 11:  # local Pakistani mobile format
        p = "+92" + p[1:]
    return p


@router.post("/register", response_model=TokenOut, status_code=201)
@limiter.limit(get_settings().rate_limit_auth)
def register(request: Request, body: RegisterIn, db: Session = Depends(get_db)):
    """Create a passenger account with email or phone and a password."""
    email = body.email.lower() if body.email else None
    phone = _normalize_phone(body.phone)
    conds = ([User.email == email] if email else []) + ([User.phone == phone] if phone else [])
    clash = db.execute(select(User).where(or_(*conds))).scalars().first()
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email or phone already exists")
    user = User(full_name=body.full_name.strip(), email=email, phone=phone, password_hash=hash_password(body.password),
                role=Role.passenger, notification_prefs=dict(DEFAULT_PREFS))
    db.add(user)
    db.commit()
    return TokenOut(access_token=create_token(user), user=user_out(user))


@router.post("/login", response_model=TokenOut)
@limiter.limit(get_settings().rate_limit_auth)
def login(request: Request, body: LoginIn, db: Session = Depends(get_db)):
    """Log in with email or phone. Works for passengers, drivers and admins."""
    ident = body.identifier.strip().lower()
    phone = _normalize_phone(ident)
    user = db.execute(select(User).where(or_(User.email == ident, User.phone == phone))).scalars().first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email/phone or password")
    if not user.is_active or (user.driver and not user.driver.is_active):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is deactivated")
    user.last_login_at = utcnow()
    db.commit()
    return TokenOut(access_token=create_token(user), user=user_out(user))


@router.post("/logout", status_code=204)
def logout(user: User = Depends(get_current_user)):
    """Tokens are stateless; the client discards its token. Kept so apps have a single logout call."""
    return None


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.patch("/me")
def update_me(body: ProfileIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.full_name:
        user.full_name = body.full_name.strip()
    if body.phone:
        phone = _normalize_phone(body.phone)
        other = db.execute(select(User).where(User.phone == phone, User.id != user.id)).scalars().first()
        if other:
            raise HTTPException(409, "Phone number already in use")
        user.phone = phone
    db.commit()
    return user_out(user)


@router.post("/me/password", status_code=204)
def change_password(body: PasswordIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    db.commit()
