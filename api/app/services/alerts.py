"""
Alert evaluation: check price thresholds and fire Telegram notifications.
Runs via APScheduler on a configurable interval.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AlertEvent, AlertRule
from app.services import pricing, telegram

logger = logging.getLogger(__name__)


async def evaluate_alerts(session: AsyncSession) -> int:
    """
    Evaluate all active alert rules against current prices.
    Creates AlertEvent records and sends Telegram messages for triggered rules.
    Returns number of alerts fired.
    """
    result = await session.execute(
        select(AlertRule).where(AlertRule.is_active == True)  # noqa: E712
    )
    rules = result.scalars().all()
    if not rules:
        return 0

    symbols = list({r.asset_symbol.upper() for r in rules})
    prices = await pricing.get_prices_bulk(symbols)

    fired = 0
    for rule in rules:
        sym = rule.asset_symbol.upper()
        price = prices.get(sym)
        if price is None:
            continue

        triggered = False
        message = ""

        if rule.condition == "price_drop_pct":
            # threshold = X% drop from avg cost basis – simplified: just absolute price
            # For now treat threshold as absolute USD price floor
            if Decimal(str(price)) <= rule.threshold:
                triggered = True
                message = (
                    f"🔴 <b>ALERT</b>: {sym} dropped to ${price:.4f} "
                    f"(threshold: ${rule.threshold})"
                )
        elif rule.condition == "price_rise_pct":
            if Decimal(str(price)) >= rule.threshold:
                triggered = True
                message = (
                    f"🟢 <b>ALERT</b>: {sym} rose to ${price:.4f} "
                    f"(threshold: ${rule.threshold})"
                )

        if triggered:
            delivered = await telegram.send_message(message)
            event = AlertEvent(
                rule_id=rule.id,
                triggered_at=datetime.now(timezone.utc),
                message=message,
                telegram_delivered=delivered,
                delivered_at=datetime.now(timezone.utc) if delivered else None,
            )
            session.add(event)
            fired += 1
            logger.info(f"Alert fired for {sym}: {message}")

    if fired:
        await session.commit()
    return fired
