from decimal import Decimal

import pytest

from app.db.models import AlertRule
from app.services.alerts import evaluate_alerts


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, rules):
        self.rules = rules
        self.events = []
        self.committed = False

    async def execute(self, statement):
        return _ScalarResult(self.rules)

    def add(self, event):
        self.events.append(event)

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_evaluate_alerts_persists_event_with_mocked_delivery(monkeypatch: pytest.MonkeyPatch):
    session = FakeSession(
        [
            AlertRule(
                id=1,
                asset_symbol="BTC",
                condition="price_drop_pct",
                threshold=Decimal("90000"),
                is_active=True,
            )
        ]
    )

    async def fake_prices(symbols):
        return {"BTC": 85000.0}

    async def fake_send(message):
        return True

    monkeypatch.setattr("app.services.alerts.pricing.get_prices_bulk", fake_prices)
    monkeypatch.setattr("app.services.alerts.telegram.send_message", fake_send)

    fired = await evaluate_alerts(session)

    assert fired == 1
    assert session.committed is True
    assert len(session.events) == 1
    assert session.events[0].telegram_delivered is True
    assert "BTC" in session.events[0].message
