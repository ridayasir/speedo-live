"""Authentication: callers send a Firebase ID token as `Authorization: Bearer <token>`.

The token is verified with the Firebase Admin SDK and mapped to the user's profile in Firestore
(users.firebase_uid). Roles (passenger, driver, admin) live on that profile.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import firebase
from .db import get_db
from .models import Role, User
from .store import Session, store

bearer = HTTPBearer(auto_error=False)


def user_by_uid(uid: str) -> User | None:
    for u in store.cached(User):
        if u.firebase_uid == uid:
            return u
    return None


def user_from_token(db: Session, token: str) -> User | None:
    if firebase.auth_provider is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Firebase Authentication is not configured")
    uid = firebase.auth_provider.verify(token)
    if not uid:
        return None
    user = user_by_uid(uid)
    if not user or not user.is_active:
        return None
    return user


def get_optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> User | None:
    if not creds:
        return None
    return user_from_token(db, creds.credentials)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> User:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", {"WWW-Authenticate": "Bearer"})
    user = user_from_token(db, creds.credentials)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", {"WWW-Authenticate": "Bearer"})
    return user


def require_role(*roles: Role):
    def dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission for this action")
        return user

    return dep


require_admin = require_role(Role.admin)
require_driver = require_role(Role.driver)
