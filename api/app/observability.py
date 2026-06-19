from __future__ import annotations

import logging
import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimitRule:
    name: str
    limit: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int
    rule_name: str


@dataclass
class _WindowCounter:
    window_started_at: int
    count: int = 0


class FixedWindowRateLimiter:
    def __init__(
        self,
        route_rules: dict[str, RateLimitRule],
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._route_rules = route_rules
        self._clock = clock or time.monotonic
        self._counters: dict[tuple[str, str], _WindowCounter] = {}
        self._lock = Lock()

    def get_rule(self, path: str) -> RateLimitRule | None:
        return self._route_rules.get(path)

    def evaluate(self, path: str, subject: str) -> RateLimitDecision | None:
        rule = self.get_rule(path)
        if rule is None:
            return None

        now = self._clock()
        window_started_at = int(now // rule.window_seconds) * rule.window_seconds
        retry_after = max(1, math.ceil(window_started_at + rule.window_seconds - now))
        counter_key = (path, subject)

        with self._lock:
            counter = self._counters.get(counter_key)
            if counter is None or counter.window_started_at != window_started_at:
                counter = _WindowCounter(window_started_at=window_started_at)
                self._counters[counter_key] = counter

            if counter.count >= rule.limit:
                return RateLimitDecision(
                    allowed=False,
                    limit=rule.limit,
                    remaining=0,
                    retry_after_seconds=retry_after,
                    rule_name=rule.name,
                )

            counter.count += 1
            return RateLimitDecision(
                allowed=True,
                limit=rule.limit,
                remaining=rule.limit - counter.count,
                retry_after_seconds=retry_after,
                rule_name=rule.name,
            )


class TelemetryCollector:
    def __init__(self, *, max_events: int = 200) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._lock = Lock()

    def record_request(
        self,
        *,
        method: str,
        path: str,
        route: str,
        status_code: int,
        duration_ms: float,
        client: str,
        rate_limited: bool,
        sensitive: bool,
        rule_name: str | None = None,
    ) -> None:
        self._record(
            {
                "event_type": "request",
                "method": method,
                "path": path,
                "route": route,
                "status_code": status_code,
                "duration_ms": round(duration_ms, 3),
                "client": client,
                "rate_limited": rate_limited,
                "sensitive": sensitive,
                "rule_name": rule_name,
            }
        )

    def record_operation(
        self,
        *,
        name: str,
        outcome: str,
        route: str,
        user_id: int | None = None,
        detail: str | None = None,
    ) -> None:
        event: dict[str, Any] = {
            "event_type": "operation",
            "name": name,
            "outcome": outcome,
            "route": route,
            "user_id": user_id,
        }
        if detail is not None:
            event["detail"] = detail
        self._record(event)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(event) for event in self._events]

    def _record(self, event: dict[str, Any]) -> None:
        enriched_event = {
            "timestamp": datetime.now(UTC).isoformat(),
            **event,
        }
        with self._lock:
            self._events.append(enriched_event)

        if enriched_event["event_type"] == "operation":
            logger.info(
                "telemetry operation=%s outcome=%s route=%s",
                enriched_event.get("name"),
                enriched_event.get("outcome"),
                enriched_event.get("route"),
            )


def build_rate_limiter_settings(
    *,
    auth_limit: int,
    auth_window_seconds: int,
    sensitive_limit: int,
    sensitive_window_seconds: int,
    clock: Callable[[], float] | None = None,
) -> FixedWindowRateLimiter:
    auth_rule = RateLimitRule(
        name="auth",
        limit=auth_limit,
        window_seconds=auth_window_seconds,
    )
    sensitive_rule = RateLimitRule(
        name="sensitive",
        limit=sensitive_limit,
        window_seconds=sensitive_window_seconds,
    )
    return FixedWindowRateLimiter(
        {
            "/v1/auth/login": auth_rule,
            "/v1/auth/refresh": auth_rule,
            "/v1/portfolio/state/refresh": sensitive_rule,
            "/v1/settings/binance-keys": sensitive_rule,
            "/v1/settings/binance-keys/rotate": sensitive_rule,
            "/v1/sync/binance": sensitive_rule,
        },
        clock=clock,
    )


def client_identifier(
    headers: Any,
    client_host: str | None,
    *,
    trust_forwarded_for: bool = False,
) -> str:
    forwarded_for = headers.get("x-forwarded-for") if headers is not None else None
    if trust_forwarded_for and forwarded_for:
        return forwarded_for.split(",", maxsplit=1)[0].strip() or (
            client_host or "unknown"
        )
    if client_host:
        return client_host
    return "unknown"
