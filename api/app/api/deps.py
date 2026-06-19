"""
FastAPI dependencies: DB session, current user extraction from JWT.
"""

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthSession, User
from app.db.session import get_db
from app.services.auth import decode_token

bearer = HTTPBearer(auto_error=True)

DBSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_session(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
    db: DBSession,
) -> AuthSession:
    token = credentials.credentials
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise ValueError("Not an access token")
        session_id = payload["sid"]
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    result = await db.execute(
        select(AuthSession).where(
            AuthSession.session_id == session_id,
            AuthSession.revoked_at.is_(None),
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session revoked or not found",
        )
    return session


async def get_current_user(
    session: Annotated[AuthSession, Depends(get_current_session)],
    db: DBSession,
) -> User:
    result = await db.execute(select(User).where(User.id == session.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    return user


CurrentSession = Annotated[AuthSession, Depends(get_current_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
