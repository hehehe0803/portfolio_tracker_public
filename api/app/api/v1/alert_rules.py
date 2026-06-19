"""
Alert rule endpoints: CRUD for price alert rules, alert event history.
"""

from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.db.models import AlertEvent, AlertRule

router = APIRouter(prefix="/alerts", tags=["alerts"])


class CreateRuleRequest(BaseModel):
    asset_symbol: str
    condition: str  # "price_drop_pct" | "price_rise_pct"
    threshold: float


@router.get("/rules")
async def list_rules(user: CurrentUser, db: DBSession):
    result = await db.execute(select(AlertRule).order_by(AlertRule.created_at.desc()))
    rules = result.scalars().all()
    return [
        {
            "id": r.id,
            "asset_symbol": r.asset_symbol,
            "condition": r.condition,
            "threshold": float(r.threshold),
            "is_active": r.is_active,
            "created_at": r.created_at.isoformat(),
        }
        for r in rules
    ]


@router.post("/rules")
async def create_rule(body: CreateRuleRequest, user: CurrentUser, db: DBSession):
    if body.condition not in ("price_drop_pct", "price_rise_pct"):
        raise HTTPException(status_code=400, detail="condition must be price_drop_pct or price_rise_pct")
    rule = AlertRule(
        asset_symbol=body.asset_symbol.upper(),
        condition=body.condition,
        threshold=Decimal(str(body.threshold)),
        is_active=True,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return {"id": rule.id, "message": "Alert rule created"}


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int, user: CurrentUser, db: DBSession):
    result = await db.execute(select(AlertRule).where(AlertRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.delete(rule)
    await db.commit()
    return {"message": "Deleted"}


@router.patch("/rules/{rule_id}/toggle")
async def toggle_rule(rule_id: int, user: CurrentUser, db: DBSession):
    result = await db.execute(select(AlertRule).where(AlertRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.is_active = not rule.is_active
    await db.commit()
    return {"is_active": rule.is_active}


@router.get("/events")
async def list_events(user: CurrentUser, db: DBSession):
    result = await db.execute(
        select(AlertEvent).order_by(AlertEvent.triggered_at.desc()).limit(100)
    )
    events = result.scalars().all()
    return [
        {
            "id": e.id,
            "rule_id": e.rule_id,
            "message": e.message,
            "telegram_delivered": e.telegram_delivered,
            "triggered_at": e.triggered_at.isoformat(),
        }
        for e in events
    ]
