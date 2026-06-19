from __future__ import annotations

from types import SimpleNamespace

from worker.jobs import run_alert_evaluation


class _AsyncSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_run_alert_evaluation_uses_session_factory(monkeypatch):
    session = SimpleNamespace(name="session")

    def fake_session_factory():
        return _AsyncSessionContext(session)

    async def fake_evaluate_alerts(db_session):
        assert db_session is session
        return 3

    monkeypatch.setattr("worker.jobs.async_session_factory", fake_session_factory)
    monkeypatch.setattr("worker.jobs.evaluate_alerts", fake_evaluate_alerts)

    assert run_alert_evaluation() == 3
