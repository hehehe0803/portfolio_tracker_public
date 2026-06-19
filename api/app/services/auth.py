"""
Auth service: password hashing, JWT tokens, TOTP.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt
import jwt
import pyotp

from app.config import settings

ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24h
REFRESH_TOKEN_EXPIRE_DAYS = 30
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def generate_session_id() -> str:
    return str(uuid4())


def generate_token_id() -> str:
    return str(uuid4())


def _encode_token(
    *,
    subject: str,
    token_type: str,
    session_id: str,
    jti: str,
    expires_at: datetime,
) -> str:
    return jwt.encode(
        {
            "sub": subject,
            "exp": expires_at,
            "type": token_type,
            "sid": session_id,
            "jti": jti,
        },
        settings.SECRET_KEY,
        algorithm=ALGORITHM,
    )


def create_access_token(subject: str, session_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return _encode_token(
        subject=subject,
        token_type="access",
        session_id=session_id,
        jti=generate_token_id(),
        expires_at=expire,
    )


def create_refresh_token(subject: str, session_id: str, refresh_jti: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    return _encode_token(
        subject=subject,
        token_type="refresh",
        session_id=session_id,
        jti=refresh_jti,
        expires_at=expire,
    )


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def get_totp_uri(secret: str, username: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=username, issuer_name="PortfolioTracker"
    )


def verify_totp(secret: str, code: str) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)
