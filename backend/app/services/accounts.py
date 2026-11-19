"""Accounts: a Firebase Authentication user (credentials) plus a Firestore profile (name, phone, role)."""
from __future__ import annotations

from fastapi import HTTPException

from .. import firebase
from ..firebase import FirebaseError, Tokens
from ..models import DEFAULT_PREFS, Role, User
from ..store import IntegrityError, Session, store

PHONE_EMAIL_DOMAIN = "phone.speedolive.invalid"


def normalize_phone(p: str | None) -> str | None:
    if not p:
        return None
    p = p.replace(" ", "").replace("-", "")
    if p.startswith("03") and len(p) == 11:  # local Pakistani mobile format
        p = "+92" + p[1:]
    return p


def _auth():
    if firebase.auth_provider is None:
        raise HTTPException(503, "Firebase Authentication is not configured")
    return firebase.auth_provider


def http_error(exc: FirebaseError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


def find_user(email: str | None = None, phone: str | None = None) -> User | None:
    for u in store.cached(User):
        if (email and u.email == email) or (phone and u.phone == phone):
            return u
    return None


def create_account(db: Session, full_name: str, password: str, role: Role, email: str | None = None,
                   phone: str | None = None) -> User:
    """Create the Firebase user and its profile. Raises HTTPException 409 if the email/phone is taken."""
    email = email.lower() if email else None
    phone = normalize_phone(phone)
    if find_user(email, phone):
        raise HTTPException(409, "An account with this email or phone already exists")
    auth_email = email or f"{phone.lstrip('+')}@{PHONE_EMAIL_DOMAIN}"
    try:
        uid = _auth().create_user(auth_email, password, full_name)
    except FirebaseError as exc:
        raise http_error(exc) from exc
    user = User(firebase_uid=uid, auth_email=auth_email, full_name=full_name.strip(), email=email, phone=phone,
                role=role, notification_prefs=dict(DEFAULT_PREFS))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _auth().delete_user(uid)
        raise HTTPException(409, "An account with this email or phone already exists") from exc
    except Exception:
        _auth().delete_user(uid)
        raise
    return user


def sign_in(db: Session, identifier: str, password: str) -> tuple[User, Tokens]:
    """Sign in with email or phone. Accounts created in the Firebase console get a passenger profile."""
    ident = identifier.strip().lower()
    if "@" in ident:
        user = find_user(email=ident) or next((u for u in store.cached(User) if u.auth_email == ident), None)
        login_email = user.auth_email if user else ident
    else:
        user = find_user(phone=normalize_phone(ident))
        if not user:
            raise HTTPException(401, "Incorrect email/phone or password")
        login_email = user.auth_email
    try:
        tokens = _auth().sign_in(login_email, password)
    except FirebaseError as exc:
        raise http_error(exc) from exc
    if user is None:  # created by another process (e.g. `python -m app.seed`) after this one started
        user = store.adopt(User, [("firebase_uid", "==", tokens.uid)])
    if user is None:
        user = User(firebase_uid=tokens.uid, auth_email=login_email, email=login_email,
                    full_name=login_email.split("@")[0], role=Role.passenger, notification_prefs=dict(DEFAULT_PREFS))
        db.add(user)
        db.commit()
    elif user.firebase_uid != tokens.uid:
        raise HTTPException(409, "This account's profile does not match its Firebase user. Contact support.")
    return user, tokens


def refresh(refresh_token: str) -> Tokens:
    try:
        return _auth().refresh(refresh_token)
    except FirebaseError as exc:
        raise http_error(exc) from exc


def set_password(user: User, password: str) -> None:
    try:
        _auth().set_password(user.firebase_uid, password)
    except FirebaseError as exc:
        raise http_error(exc) from exc


def set_active(user: User, active: bool) -> None:
    """Deactivated accounts are also disabled in Firebase, so they cannot sign in or refresh tokens."""
    _auth().set_disabled(user.firebase_uid, not active)


def token_out(user: User, tokens: Tokens) -> dict:
    from ..schemas import user_out

    return {"access_token": tokens.id_token, "token_type": "bearer", "refresh_token": tokens.refresh_token,
            "expires_in": tokens.expires_in, "user": user_out(user)}
