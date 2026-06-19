"""
Auth endpoints: login, refresh, TOTP setup/verify, change password.
"""

import base64
import io
from datetime import UTC, datetime

import qrcode
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentSession, CurrentUser, DBSession
from app.db.models import AuthSession, User
from app.services.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_session_id,
    generate_token_id,
    generate_totp_secret,
    get_totp_uri,
    hash_password,
    verify_password,
    verify_totp,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    totp_required: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class TOTPSetupResponse(BaseModel):
    secret: str
    qr_code_base64: str
    uri: str


class TOTPVerifyRequest(BaseModel):
    code: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: DBSession) -> TokenResponse:
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    # If TOTP is enabled, require code
    if user.totp_enabled:
        if not body.totp_code:
            return TokenResponse(
                access_token="",
                refresh_token="",
                totp_required=True,
            )
        if not verify_totp(user.totp_secret, body.totp_code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP code"
            )

    session = AuthSession(
        session_id=generate_session_id(),
        user_id=user.id,
        refresh_jti=generate_token_id(),
    )
    db.add(session)
    await db.commit()

    return TokenResponse(
        access_token=create_access_token(user.username, session.session_id),
        refresh_token=create_refresh_token(
            user.username, session.session_id, session.refresh_jti
        ),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest, request: Request, db: DBSession
) -> TokenResponse:
    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise ValueError
        username = payload["sub"]
        session_id = payload["sid"]
        refresh_jti = payload["jti"]
    except Exception:
        request.app.state.telemetry.record_operation(
            name="auth.refresh",
            outcome="rejected",
            route="/v1/auth/refresh",
            detail="invalid_refresh_token",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from None

    session_result = await db.execute(
        select(AuthSession).where(AuthSession.session_id == session_id)
    )
    session = session_result.scalar_one_or_none()
    if (
        session is None
        or session.revoked_at is not None
        or session.refresh_jti != refresh_jti
    ):
        request.app.state.telemetry.record_operation(
            name="auth.refresh",
            outcome="rejected",
            route="/v1/auth/refresh",
            detail="session_not_refreshable",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    user_result = await db.execute(select(User).where(User.username == username))
    user = user_result.scalar_one_or_none()
    if user is None or user.id != session.user_id:
        request.app.state.telemetry.record_operation(
            name="auth.refresh",
            outcome="rejected",
            route="/v1/auth/refresh",
            detail="user_not_found",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )

    session.refresh_jti = generate_token_id()
    session.last_refreshed_at = datetime.now(UTC)
    await db.commit()
    request.app.state.telemetry.record_operation(
        name="auth.refresh",
        outcome="success",
        route="/v1/auth/refresh",
        user_id=user.id,
    )

    return TokenResponse(
        access_token=create_access_token(username, session.session_id),
        refresh_token=create_refresh_token(
            username, session.session_id, session.refresh_jti
        ),
    )


@router.get("/me")
async def me(user: CurrentUser):
    return {
        "id": user.id,
        "username": user.username,
        "totp_enabled": user.totp_enabled,
        "telegram_configured": bool(user.telegram_chat_id),
    }


@router.post("/logout")
async def logout(session: CurrentSession, db: DBSession):
    session.revoked_at = datetime.now(UTC)
    await db.commit()
    return {"message": "Logged out"}


@router.post("/totp/setup", response_model=TOTPSetupResponse)
async def totp_setup(user: CurrentUser, db: DBSession) -> TOTPSetupResponse:
    if user.totp_enabled:
        raise HTTPException(status_code=400, detail="TOTP is already enabled")

    secret = generate_totp_secret()
    uri = get_totp_uri(secret, user.username)

    # Generate QR code as base64
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    # Store secret (not yet enabled until verified)
    user.totp_secret = secret
    await db.commit()

    return TOTPSetupResponse(secret=secret, qr_code_base64=qr_b64, uri=uri)


@router.post("/totp/verify")
async def totp_verify(body: TOTPVerifyRequest, user: CurrentUser, db: DBSession):
    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="Run /totp/setup first")
    if not verify_totp(user.totp_secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    user.totp_enabled = True
    await db.commit()
    return {"message": "TOTP enabled successfully"}


@router.post("/totp/disable")
async def totp_disable(body: TOTPVerifyRequest, user: CurrentUser, db: DBSession):
    if not user.totp_enabled:
        raise HTTPException(status_code=400, detail="TOTP is not enabled")
    if not verify_totp(user.totp_secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    user.totp_enabled = False
    user.totp_secret = None
    await db.commit()
    return {"message": "TOTP disabled"}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest, user: CurrentUser, db: DBSession
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"message": "Password changed"}
