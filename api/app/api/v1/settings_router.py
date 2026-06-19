"""
Settings endpoints: Binance API key config, Telegram binding.
"""

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.db.models import ActivityLog, Institution
from app.services.credentials import CredentialConfigError

router = APIRouter(prefix="/settings", tags=["settings"])


class BinanceKeysRequest(BaseModel):
    api_key: str = Field(min_length=1)
    api_secret: str = Field(min_length=1)


class RotateBinanceKeysRequest(BinanceKeysRequest):
    reason: str | None = None


class TelegramRequest(BaseModel):
    chat_id: str


def _log_binance_credential_event(
    user_id: int,
    status: str,
    message: str,
) -> ActivityLog:
    return ActivityLog(
        source="settings.binance_credentials",
        status=status,
        message=message,
        user_id=user_id,
    )


def _raise_credential_encryption_unavailable() -> None:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Institution credential encryption is not configured",
    )


@router.post("/binance-keys")
async def set_binance_keys(
    body: BinanceKeysRequest,
    user: CurrentUser,
    request: Request,
    db: DBSession,
):
    result = await db.execute(select(Institution).where(Institution.name == "binance"))
    inst = result.scalar_one_or_none()
    if inst is None:
        inst = Institution(name="binance")
        db.add(inst)

    try:
        inst.set_api_credentials(body.api_key, body.api_secret, rotated=False)
    except CredentialConfigError:
        request.app.state.telemetry.record_operation(
            name="settings.binance_credentials.update",
            outcome="failed",
            route="/v1/settings/binance-keys",
            user_id=user.id,
            detail="credential_encryption_unavailable",
        )
        _raise_credential_encryption_unavailable()
    db.add(
        _log_binance_credential_event(
            user.id,
            "updated",
            "Stored encrypted Binance API credentials",
        )
    )
    await db.commit()
    await db.refresh(inst)
    request.app.state.telemetry.record_operation(
        name="settings.binance_credentials.update",
        outcome="success",
        route="/v1/settings/binance-keys",
        user_id=user.id,
    )
    return {
        "message": "Binance keys updated",
        "rotated": False,
        "credential_updated_at": inst.credentials_updated_at.isoformat(),
    }


@router.post("/binance-keys/rotate")
async def rotate_binance_keys(
    body: RotateBinanceKeysRequest,
    user: CurrentUser,
    request: Request,
    db: DBSession,
):
    result = await db.execute(select(Institution).where(Institution.name == "binance"))
    inst = result.scalar_one_or_none()
    if inst is None:
        inst = Institution(name="binance")
        db.add(inst)

    try:
        inst.set_api_credentials(body.api_key, body.api_secret, rotated=True)
    except CredentialConfigError:
        request.app.state.telemetry.record_operation(
            name="settings.binance_credentials.rotate",
            outcome="failed",
            route="/v1/settings/binance-keys/rotate",
            user_id=user.id,
            detail="credential_encryption_unavailable",
        )
        _raise_credential_encryption_unavailable()
    reason_suffix = f" ({body.reason})" if body.reason else ""
    db.add(
        _log_binance_credential_event(
            user.id,
            "rotated",
            f"Rotated encrypted Binance API credentials{reason_suffix}",
        )
    )
    await db.commit()
    await db.refresh(inst)
    request.app.state.telemetry.record_operation(
        name="settings.binance_credentials.rotate",
        outcome="success",
        route="/v1/settings/binance-keys/rotate",
        user_id=user.id,
    )
    return {
        "message": "Binance keys rotated",
        "rotated": True,
        "credential_updated_at": inst.credentials_updated_at.isoformat(),
        "rotation_count": inst.credential_rotation_count,
    }


@router.post("/telegram")
async def set_telegram(body: TelegramRequest, user: CurrentUser, db: DBSession):
    user.telegram_chat_id = body.chat_id
    await db.commit()
    return {"message": "Telegram chat ID saved"}
