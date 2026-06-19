"""
Sync endpoints: trigger Binance sync, get sync status.
"""

from redis import RedisError
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.db.models import ActivityLog, Institution
from app.services.credentials import CredentialConfigError, InvalidCredentialError
from app.services.scheduler_jobs import (
    execute_binance_auto_sync,
    get_freshness_status,
    get_redis_connection,
)

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/binance")
async def trigger_binance_sync(user: CurrentUser, request: Request, db: DBSession):
    """Trigger a manual Binance balance snapshot sync."""
    user_id = user.id
    try:
        redis_connection = get_redis_connection()
        redis_connection.ping()
        result = await execute_binance_auto_sync(
            db,
            redis_connection=redis_connection,
            respect_enabled=False,
            degrade_credential_errors=False,
            source="sync.binance",
        )
    except RedisError as exc:
        request.app.state.telemetry.record_operation(
            name="sync.binance",
            outcome="failed",
            route="/v1/sync/binance",
            user_id=user_id,
            detail="sync_lock_unavailable",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Binance sync lock is unavailable; check Redis",
        ) from exc
    except CredentialConfigError as exc:
        request.app.state.telemetry.record_operation(
            name="sync.binance",
            outcome="failed",
            route="/v1/sync/binance",
            user_id=user_id,
            detail="credential_encryption_unavailable",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Institution credential encryption is not configured",
        ) from exc
    except InvalidCredentialError as exc:
        request.app.state.telemetry.record_operation(
            name="sync.binance",
            outcome="failed",
            route="/v1/sync/binance",
            user_id=user_id,
            detail="stored_credentials_unreadable",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stored Binance credentials could not be decrypted",
        ) from exc

    outcome = result.get("status") or ("degraded" if result.get("degraded") else "success")
    detail = result.get("error")
    if not detail and result.get("warnings"):
        detail = "; ".join(result["warnings"])
    request.app.state.telemetry.record_operation(
        name="sync.binance",
        outcome=outcome,
        route="/v1/sync/binance",
        user_id=user_id,
        detail=detail,
    )
    return result


@router.get("/status")
async def sync_status(user: CurrentUser, db: DBSession):
    return await _institution_sync_statuses(db)


@router.get("/freshness")
async def sync_freshness(user: CurrentUser, db: DBSession):
    return await get_freshness_status(db)


async def _institution_sync_statuses(db: DBSession):
    result = await db.execute(select(Institution))
    institutions = result.scalars().all()
    activity_result = await db.execute(
        select(ActivityLog)
        .where(ActivityLog.source == "sync.binance")
        .order_by(ActivityLog.created_at.desc())
    )
    latest_sync_activity = activity_result.scalars().first()
    return [
        {
            "name": inst.name,
            "last_sync_at": (
                inst.last_sync_at.isoformat() if inst.last_sync_at else None
            ),
            "degraded": (
                latest_sync_activity.status == "degraded"
                if inst.name == "binance" and latest_sync_activity is not None
                else False
            ),
            "warning": (
                latest_sync_activity.message
                if inst.name == "binance"
                and latest_sync_activity is not None
                and latest_sync_activity.status == "degraded"
                else None
            ),
            "note": (
                (
                    "API delta sync currently covers deposits, withdrawals, convert, "
                    "Simple Earn, and C2C/P2P only. Spot trades, internal transfers, "
                    "dividends, and dust remain export-only; import a fresh Binance "
                    "export after that activity."
                )
                if inst.name == "binance"
                else None
            ),
        }
        for inst in institutions
    ]
