from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DBSession
from app.db.models import (
    ActivityLog,
    Asset,
    Note,
    WatchlistItem,
    utcnow,
)
from app.services.accounting_review import (
    AccountingReviewDecisionConflict,
    AccountingReviewError,
    AccountingReviewNotFound,
    approve_accounting_review_decision,
    list_open_accounting_review_tasks,
)
from shared.python.contracts import (
    AccountingReviewDecisionRequest,
    AccountingReviewDecisionResponse,
    AccountingReviewQueue,
)

router = APIRouter(prefix="/review", tags=["review"])

DecisionAction = Literal["hold", "add", "trim", "exit", "research", "snooze", "archive"]
EntityType = Literal["asset", "watchlist", "portfolio", "system"]
ALLOWED_DECISIONS = ["hold", "add", "trim", "exit", "research", "snooze", "archive"]
ACTIVE_WATCHLIST_STATUSES = {"idea", "researching", "ready", "paused"}


class ReviewDecisionIn(BaseModel):
    entity_type: EntityType
    entity_id: str = Field(min_length=1, max_length=80)
    decision: str = Field(min_length=1, max_length=30)
    rationale: str | None = None
    next_review_date: date | None = None


def _parse_as_of(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _date_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _to_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _entity_key(entity_type: str, entity_id: str) -> str:
    normalized = entity_id.upper() if entity_type == "asset" else entity_id
    return f"{entity_type}:{normalized}"


def _decision_json(log: ActivityLog) -> dict:
    metadata = log.event_metadata or {}
    return {
        "id": log.id,
        "entity_type": metadata.get("entity_type"),
        "entity_id": metadata.get("entity_id"),
        "decision": log.status,
        "rationale": metadata.get("rationale"),
        "next_review_date": metadata.get("next_review_date"),
        "created_at": log.created_at.isoformat(),
    }


def _item(
    *,
    key: str,
    entity_type: str,
    entity_id: str,
    title: str,
    reasons: list[str],
    priority: str = "medium",
    metadata: dict | None = None,
) -> dict:
    return {
        "key": key,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "title": title,
        "reasons": reasons,
        "priority": priority,
        "metadata": metadata or {},
    }


async def _future_review_keys(db: DBSession, as_of: datetime) -> set[str]:
    logs = (
        (
            await db.execute(
                select(ActivityLog).where(ActivityLog.source == "review_decision")
            )
        )
        .scalars()
        .all()
    )
    future: set[str] = set()
    for log in logs:
        metadata = log.event_metadata or {}
        entity_type = metadata.get("entity_type")
        entity_id = metadata.get("entity_id")
        next_review_date = metadata.get("next_review_date")
        if not entity_type or not entity_id or not next_review_date:
            continue
        try:
            due_at = _date_start(date.fromisoformat(str(next_review_date)))
        except ValueError:
            continue
        if due_at > as_of:
            future.add(_entity_key(str(entity_type), str(entity_id)))
    return future


@router.get("/queue")
async def review_queue(
    user: CurrentUser,
    db: DBSession,
    as_of: datetime | None = None,
    stale_note_days: Annotated[int, Query(ge=1, le=730)] = 90,
    major_pnl_pct: Annotated[Decimal, Query(ge=Decimal("0"))] = Decimal("0.20"),
    event_lookback_days: Annotated[int, Query(ge=1, le=90)] = 7,
):
    now = _parse_as_of(as_of)
    future_review_keys = await _future_review_keys(db, now)
    items_by_key: dict[str, dict] = {}

    assets = (
        (
            await db.execute(
                select(Asset)
                .options(selectinload(Asset.position_snapshots))
                .order_by(Asset.symbol.asc())
            )
        )
        .scalars()
        .all()
    )
    notes = (
        (
            await db.execute(
                select(Note)
                .where(Note.deleted_at.is_(None))
                .order_by(Note.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    active_asset_note_symbols = {
        note.entity_id.upper()
        for note in notes
        if note.entity_type == "asset" and note.entity_id
    }
    stale_cutoff = now - timedelta(days=stale_note_days)
    stale_asset_note_symbols = {
        note.entity_id.upper()
        for note in notes
        if note.entity_type == "asset"
        and ((note.updated_at or note.created_at).astimezone(UTC) <= stale_cutoff)
    }

    for asset in assets:
        latest_snapshot = max(
            asset.position_snapshots, key=lambda row: row.captured_at, default=None
        )
        if latest_snapshot is None:
            continue
        key = _entity_key("asset", asset.symbol)
        if key in future_review_keys:
            continue
        reasons: list[str] = []
        if asset.symbol not in active_asset_note_symbols:
            reasons.append("missing_thesis")
        if asset.thesis_status in {"none", "unknown", ""}:
            reasons.append("missing_status")
        reasons.append("missing_review_date")
        if (
            latest_snapshot.unrealized_pnl_pct is not None
            and abs(latest_snapshot.unrealized_pnl_pct) >= major_pnl_pct
        ):
            reasons.append("major_unrealized_pnl_move")
        if asset.symbol in stale_asset_note_symbols:
            reasons.append("stale_note")
        if reasons:
            items_by_key[key] = _item(
                key=key,
                entity_type="asset",
                entity_id=asset.symbol,
                title=f"{asset.symbol} holding review",
                reasons=list(dict.fromkeys(reasons)),
                priority="high" if "major_unrealized_pnl_move" in reasons else "medium",
                metadata={
                    "current_value_usd": _to_float(latest_snapshot.current_value_usd),
                    "unrealized_pnl_pct": _to_float(latest_snapshot.unrealized_pnl_pct),
                    "snapshot_at": latest_snapshot.captured_at.isoformat(),
                    "thesis_status": asset.thesis_status,
                },
            )

    watchlist_items = (
        (
            await db.execute(
                select(WatchlistItem).where(
                    WatchlistItem.status.in_(ACTIVE_WATCHLIST_STATUSES)
                )
            )
        )
        .scalars()
        .all()
    )
    for watch in watchlist_items:
        key = _entity_key("watchlist", watch.symbol)
        if key in future_review_keys:
            continue
        if (
            watch.next_review_date is not None
            and _date_start(watch.next_review_date) <= now
        ):
            items_by_key[key] = _item(
                key=key,
                entity_type="watchlist",
                entity_id=watch.symbol,
                title=f"{watch.symbol} watchlist review",
                reasons=["watchlist_review_due"],
                priority=watch.priority,
                metadata={
                    "status": watch.status,
                    "next_review_date": watch.next_review_date.isoformat(),
                    "target_entry_min": _to_float(watch.target_entry_min),
                    "target_entry_max": _to_float(watch.target_entry_max),
                },
            )

    event_cutoff = now - timedelta(days=event_lookback_days)
    broker_events = (
        (
            await db.execute(
                select(ActivityLog)
                .where(ActivityLog.created_at >= event_cutoff)
                .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
            )
        )
        .scalars()
        .all()
    )
    seen_event_sources: set[str] = set()
    for event in broker_events:
        if not (
            event.source.startswith("sync.")
            or event.source.startswith("imports.")
            or event.source.startswith("import")
        ):
            continue
        if event.source in seen_event_sources:
            continue
        seen_event_sources.add(event.source)
        key = f"event:{event.source}"
        items_by_key[key] = _item(
            key=key,
            entity_type="system",
            entity_id=event.source,
            title=f"Review new broker event: {event.source}",
            reasons=["new_broker_event"],
            priority="medium",
            metadata={
                "status": event.status,
                "message": event.message,
                "created_at": event.created_at.isoformat(),
                "event_metadata": event.event_metadata or {},
            },
        )

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    items = sorted(
        items_by_key.values(),
        key=lambda row: (
            priority_rank.get(row["priority"], 1),
            row["entity_type"],
            row["entity_id"],
        ),
    )
    return {
        "as_of": now.isoformat(),
        "allowed_decisions": ALLOWED_DECISIONS,
        "items": items,
    }


@router.get("/accounting/tasks", response_model=AccountingReviewQueue)
async def accounting_review_tasks(user: CurrentUser, db: DBSession):
    return await list_open_accounting_review_tasks(db)


@router.post(
    "/accounting/decisions",
    response_model=AccountingReviewDecisionResponse,
)
async def record_accounting_review_decision(
    payload: AccountingReviewDecisionRequest,
    user: CurrentUser,
    db: DBSession,
):
    try:
        response = await approve_accounting_review_decision(
            db,
            payload,
            user_id=user.id,
            username=getattr(user, "username", None) or "local_user",
        )
    except AccountingReviewNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AccountingReviewDecisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AccountingReviewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return response


@router.post("/decisions")
async def record_review_decision(
    payload: ReviewDecisionIn, user: CurrentUser, db: DBSession
):
    if payload.decision not in ALLOWED_DECISIONS:
        raise HTTPException(status_code=400, detail="Unsupported review decision")
    entity_id = (
        payload.entity_id.upper()
        if payload.entity_type == "asset"
        else payload.entity_id
    )
    metadata = {
        "entity_type": payload.entity_type,
        "entity_id": entity_id,
        "decision": payload.decision,
        "rationale": payload.rationale,
        "next_review_date": (
            payload.next_review_date.isoformat() if payload.next_review_date else None
        ),
    }
    log = ActivityLog(
        source="review_decision",
        status=payload.decision,
        message=(
            f"Review decision {payload.decision} for {payload.entity_type}:{entity_id}"
        ),
        user_id=user.id,
        event_metadata=metadata,
        created_at=utcnow(),
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return _decision_json(log)


@router.get("/decisions")
async def list_review_decisions(
    user: CurrentUser,
    db: DBSession,
    entity_type: EntityType | None = None,
    entity_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    q = (
        select(ActivityLog)
        .where(ActivityLog.source == "review_decision")
        .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
        .limit(limit)
    )
    if entity_type:
        q = q.where(
            ActivityLog.event_metadata["entity_type"].as_string() == entity_type
        )
    if entity_id:
        normalized = entity_id.upper() if entity_type == "asset" else entity_id
        q = q.where(ActivityLog.event_metadata["entity_id"].as_string() == normalized)
    rows = (await db.execute(q)).scalars().all()
    return [_decision_json(row) for row in rows]
