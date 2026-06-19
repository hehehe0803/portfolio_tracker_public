from redis import Redis
from rq import Queue

from app.config import settings


def get_redis_connection(url: str | None = None) -> Redis:
    return Redis.from_url(url or settings.REDIS_URL)


def get_queue(connection: Redis | None = None, is_async: bool = True) -> Queue:
    return Queue("default", connection=connection or get_redis_connection(), is_async=is_async)
