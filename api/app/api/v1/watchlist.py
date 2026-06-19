from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.db.models import ActivityLog, Asset, WatchlistItem, WatchlistTargetAlert
from app.services import pricing, telegram

router = APIRouter(prefix="/watchlist", tags=["watchlist"])
PRIORITIES = {"low", "medium", "high"}
STATUSES = {"idea", "researching", "ready", "paused", "promoted", "archived"}
WATCHLIST_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,19}$")


class WatchlistIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    name: str | None = Field(default=None, max_length=120)
    market: str | None = Field(default=None, max_length=30)
    asset_type: str = Field(default="unknown", max_length=20)
    priority: str = Field(default="medium", max_length=20)
    status: str = Field(default="idea", max_length=20)
    target_entry_min: Decimal | None = None
    target_entry_max: Decimal | None = None
    thesis: str | None = None
    catalyst: str | None = None
    next_review_date: date | None = None
    owned_asset_id: int | None = None


class WatchlistPatch(BaseModel):
    symbol: str | None = Field(default=None, min_length=1, max_length=20)
    name: str | None = Field(default=None, max_length=120)
    market: str | None = Field(default=None, max_length=30)
    asset_type: str | None = Field(default=None, max_length=20)
    priority: str | None = Field(default=None, max_length=20)
    status: str | None = Field(default=None, max_length=20)
    target_entry_min: Decimal | None = None
    target_entry_max: Decimal | None = None
    thesis: str | None = None
    catalyst: str | None = None
    next_review_date: date | None = None
    owned_asset_id: int | None = None


def _validate_symbol(symbol: str) -> str:
    normalized = symbol.upper()
    if not WATCHLIST_SYMBOL_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=400, detail="Unsupported watchlist symbol")
    return normalized


def _validate(payload: WatchlistIn) -> None:
    _validate_symbol(payload.symbol)
    if payload.priority not in PRIORITIES:
        raise HTTPException(status_code=400, detail="Unsupported priority")
    if payload.status not in STATUSES:
        raise HTTPException(status_code=400, detail="Unsupported status")
    if (
        payload.target_entry_min is not None
        and payload.target_entry_max is not None
        and payload.target_entry_min > payload.target_entry_max
    ):
        raise HTTPException(
            status_code=400, detail="target_entry_min must be <= target_entry_max"
        )


def _validate_values(values: dict[str, Any]) -> None:
    symbol = values.get("symbol")
    if symbol is not None:
        _validate_symbol(symbol)
    priority = values.get("priority")
    status = values.get("status")
    if priority is not None and priority not in PRIORITIES:
        raise HTTPException(status_code=400, detail="Unsupported priority")
    if status is not None and status not in STATUSES:
        raise HTTPException(status_code=400, detail="Unsupported status")
    target_min = values.get("target_entry_min")
    target_max = values.get("target_entry_max")
    if target_min is not None and target_max is not None and target_min > target_max:
        raise HTTPException(
            status_code=400, detail="target_entry_min must be <= target_entry_max"
        )


def _freshness_metadata(
    *,
    source: str,
    as_of: datetime | None,
    stale: bool = False,
    degraded: bool = False,
    fallback: bool = False,
    warnings: list[str] | None = None,
) -> dict:
    return {
        "source": source,
        "as_of": as_of.isoformat() if as_of is not None else None,
        "stale": stale,
        "degraded": degraded,
        "fallback": fallback,
        "warnings": warnings or [],
    }


def _json(
    item: WatchlistItem,
    *,
    current_price_usd: float | None = None,
    priced_at: datetime | None = None,
) -> dict:
    if current_price_usd is None:
        freshness = _freshness_metadata(
            source="not_priced",
            as_of=priced_at,
            degraded=True,
            stale=True,
            warnings=[f"{item.symbol} has no watchlist price metadata"],
        )
    else:
        freshness = _freshness_metadata(
            source="live_price_provider",
            as_of=priced_at,
        )
    return {
        "id": item.id,
        "symbol": item.symbol,
        "name": item.name,
        "market": item.market,
        "asset_type": item.asset_type,
        "priority": item.priority,
        "status": item.status,
        "target_entry_min": float(item.target_entry_min)
        if item.target_entry_min is not None
        else None,
        "target_entry_max": float(item.target_entry_max)
        if item.target_entry_max is not None
        else None,
        "thesis": item.thesis,
        "catalyst": item.catalyst,
        "next_review_date": item.next_review_date.isoformat()
        if item.next_review_date
        else None,
        "owned_asset_id": item.owned_asset_id,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "current_price_usd": current_price_usd,
        "freshness": freshness,
    }


@router.post("")
async def create_item(payload: WatchlistIn, user: CurrentUser, db: DBSession):
    _validate(payload)
    data = payload.model_dump()
    data["symbol"] = _validate_symbol(payload.symbol)
    item = WatchlistItem(**data)
    db.add(item)
    await db.flush()
    db.add(
        ActivityLog(
            source="watchlist",
            status="created",
            message=f"Watchlist item created for {item.symbol}",
            user_id=user.id,
            event_metadata={
                "entity_type": "watchlist",
                "entity_id": str(item.id),
                "symbol": item.symbol,
            },
        )
    )
    await db.commit()
    await db.refresh(item)
    return _json(item)


@router.get("")
async def list_items(
    user: CurrentUser,
    db: DBSession,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=200),
):
    q = (
        select(WatchlistItem)
        .order_by(WatchlistItem.priority.desc(), WatchlistItem.symbol.asc())
        .limit(limit)
    )
    if status:
        q = q.where(WatchlistItem.status == status)
    items = (await db.execute(q)).scalars().all()
    priced_at = datetime.now(UTC)
    prices = (
        await pricing.get_prices_bulk([item.symbol for item in items]) if items else {}
    )
    return [
        _json(item, current_price_usd=prices.get(item.symbol), priced_at=priced_at)
        for item in items
    ]


@router.get("/{item_id}")
async def get_item(item_id: int, user: CurrentUser, db: DBSession):
    item = await db.get(WatchlistItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    return _json(item)


@router.patch("/{item_id}")
async def update_item(
    item_id: int, payload: WatchlistPatch, user: CurrentUser, db: DBSession
):
    item = await db.get(WatchlistItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    updates = payload.model_dump(exclude_unset=True)
    merged = {
        "priority": item.priority,
        "status": item.status,
        "target_entry_min": item.target_entry_min,
        "target_entry_max": item.target_entry_max,
        **updates,
    }
    _validate_values(merged)
    for key, value in updates.items():
        setattr(item, key, value)
    if payload.symbol is not None:
        item.symbol = _validate_symbol(payload.symbol)
    from app.db.models import utcnow

    item.updated_at = utcnow()
    db.add(
        ActivityLog(
            source="watchlist",
            status="updated",
            message=f"Watchlist item updated for {item.symbol}",
            user_id=user.id,
            event_metadata={
                "entity_type": "watchlist",
                "entity_id": str(item.id),
                "symbol": item.symbol,
            },
        )
    )
    await db.commit()
    await db.refresh(item)
    return _json(item)


@router.delete("/{item_id}")
async def delete_item(item_id: int, user: CurrentUser, db: DBSession):
    item = await db.get(WatchlistItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    await db.delete(item)
    await db.commit()
    return {"message": "Deleted"}


@router.post("/{item_id}/promote/{symbol}")
async def link_owned_asset(item_id: int, symbol: str, user: CurrentUser, db: DBSession):
    item = await db.get(WatchlistItem, item_id)
    asset = await db.scalar(select(Asset).where(Asset.symbol == symbol.upper()))
    if item is None or asset is None:
        raise HTTPException(status_code=404, detail="Watchlist item or asset not found")
    item.owned_asset_id = asset.id
    item.status = "promoted"
    await db.commit()
    await db.refresh(item)
    return _json(item)


@router.post("/alerts/evaluate")
async def evaluate_targets(user: CurrentUser, db: DBSession):
    items = (
        (
            await db.execute(
                select(WatchlistItem).where(
                    WatchlistItem.target_entry_max.is_not(None),
                    WatchlistItem.status.notin_(["archived", "promoted"]),
                )
            )
        )
        .scalars()
        .all()
    )
    prices = await pricing.get_prices_bulk([i.symbol for i in items])
    triggered = []
    for item in items:
        latest = prices.get(item.symbol)
        if latest is None or Decimal(str(latest)) > item.target_entry_max:
            continue
        exists = await db.scalar(
            select(WatchlistTargetAlert).where(
                WatchlistTargetAlert.watchlist_item_id == item.id
            )
        )
        if exists is not None:
            continue
        message = (
            f"{item.symbol} is at or below target entry: "
            f"{latest} <= {item.target_entry_max}"
        )
        delivered = await telegram.send_message(f"🎯 <b>WATCHLIST</b>: {message}")
        from app.db.models import utcnow

        alert = WatchlistTargetAlert(
            watchlist_item_id=item.id,
            trigger_price=Decimal(str(latest)),
            target_entry_max=item.target_entry_max,
            message=message,
            telegram_delivered=delivered,
            delivered_at=utcnow() if delivered else None,
        )
        db.add(alert)
        db.add(
            ActivityLog(
                source="watchlist_alert",
                status="triggered",
                message=alert.message,
                user_id=user.id,
                event_metadata={
                    "entity_type": "watchlist",
                    "entity_id": str(item.id),
                    "symbol": item.symbol,
                },
            )
        )
        triggered.append(
            {
                "watchlist_item_id": item.id,
                "symbol": item.symbol,
                "trigger_price": float(latest),
                "target_entry_max": float(item.target_entry_max),
            }
        )
    await db.commit()
    return {"triggered": triggered}


@router.get("/alerts/events")
async def alert_events(user: CurrentUser, db: DBSession):
    rows = (
        (
            await db.execute(
                select(WatchlistTargetAlert).order_by(
                    WatchlistTargetAlert.triggered_at.desc()
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": r.id,
            "watchlist_item_id": r.watchlist_item_id,
            "trigger_price": float(r.trigger_price),
            "target_entry_max": float(r.target_entry_max),
            "message": r.message,
            "telegram_delivered": r.telegram_delivered,
            "delivered_at": r.delivered_at.isoformat() if r.delivered_at else None,
            "triggered_at": r.triggered_at.isoformat(),
        }
        for r in rows
    ]
