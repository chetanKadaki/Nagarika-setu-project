import hashlib
import hmac
import secrets
import time
import uuid
from datetime import datetime, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.exceptions import GoogleAuthError, TransportError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import AuthSession, User, UserAuthentication

bearer = HTTPBearer(auto_error=False)
TOKEN_ISSUER = "civicai"
TOKEN_AUDIENCE = "civicai-api"
TOKEN_TTL_SECONDS = 30 * 60
_DUMMY_PASSWORD_HASH = "pbkdf2_sha256$600000$00000000000000000000000000000000$" + "0" * 64


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 128:
        raise ValueError("Passwords must contain at least 12 characters.")
    actual_salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), actual_salt, 600_000)
    return f"pbkdf2_sha256$600000${actual_salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        if len(password) > 128:
            return False
        scheme, iterations, salt_hex, digest_hex = password_hash.split("$", maxsplit=3)
        if scheme != "pbkdf2_sha256" or int(iterations) != 600_000:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        if len(salt) != 16 or len(expected) != 32:
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
        return hmac.compare_digest(candidate, expected)
    except (ValueError, TypeError):
        return False


def verify_unknown_user_password(password: str) -> None:
    verify_password(password, _DUMMY_PASSWORD_HASH)


def verify_google_id_token(credential: str, client_id: str) -> dict:
    try:
        return id_token.verify_oauth2_token(
            credential,
            GoogleRequest(),
            audience=client_id,
        )
    except TransportError as error:
        raise HTTPException(
            status_code=503,
            detail="Google sign-in verification is temporarily unavailable.",
        ) from error
    except (GoogleAuthError, ValueError) as error:
        raise HTTPException(status_code=401, detail="Google sign-in could not be verified.") from error


def create_access_token(user: User) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": user.id,
            "iat": now,
            "exp": now + TOKEN_TTL_SECONDS,
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def create_session_access_token(user: User, db: Session) -> str:
    now = int(time.time())
    session_id = str(uuid.uuid4())
    expires_at = datetime.fromtimestamp(now + TOKEN_TTL_SECONDS, timezone.utc)
    db.add(AuthSession(id=session_id, user_id=user.id, expires_at=expires_at))
    return jwt.encode(
        {
            "sub": user.id,
            "jti": session_id,
            "iat": now,
            "exp": now + TOKEN_TTL_SECONDS,
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def revoke_session_access_token(token: str, user: User, db: Session) -> None:
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        issuer=TOKEN_ISSUER,
        audience=TOKEN_AUDIENCE,
        options={"require": ["sub", "iat", "exp", "iss", "aud"]},
    )
    if payload.get("sub") != user.id:
        raise jwt.InvalidTokenError("Token subject does not match the current user.")
    session_id = payload.get("jti")
    if isinstance(session_id, str):
        auth_session = db.get(AuthSession, session_id)
        if auth_session is not None and auth_session.user_id == user.id:
            auth_session.revoked_at = datetime.now(timezone.utc)
            db.commit()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=401,
        detail="A valid sign-in is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    if len(credentials.credentials) > 4096:
        raise unauthorized
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=["HS256"],
            issuer=TOKEN_ISSUER,
            audience=TOKEN_AUDIENCE,
            options={"require": ["sub", "iat", "exp", "iss", "aud"]},
        )
        subject = payload.get("sub")
        if not isinstance(subject, str):
            raise unauthorized
        user = db.get(User, subject)
        if user is None:
            raise unauthorized
        session_id = payload.get("jti")
        if not isinstance(session_id, str) and settings.environment.lower() != "test":
            raise unauthorized
        if isinstance(session_id, str):
            auth_session = db.get(AuthSession, session_id)
            if auth_session is None or auth_session.user_id != user.id or auth_session.revoked_at is not None:
                raise unauthorized
            expires_at = auth_session.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                raise unauthorized
        account = db.get(UserAuthentication, user.id)
        if account is not None and (
            account.account_status != "ACTIVE" or not account.email_verified
        ):
            raise unauthorized
        return user
    except jwt.InvalidTokenError:
        raise unauthorized from None


def require_role(*roles: str):
    if not roles:
        raise ValueError("At least one permitted role must be specified.")

    def role_dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Your account cannot perform this action.")
        return user

    return role_dependency
