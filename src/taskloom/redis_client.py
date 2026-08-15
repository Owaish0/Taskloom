from redis.asyncio import Redis

from taskloom.config import settings

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        # redis-py defaults socket_timeout to 5s (for its maintenance-notification
        # handling), independent of any per-command timeout we pass — e.g. BLPOP's
        # own blocking timeout. With a poll timeout >= 5s that races the client's
        # own read-timeout watchdog against the server's blocking-wait timer and
        # the client can lose, raising spuriously instead of getting a clean nil
        # reply. Give the socket a generous cushion above our longest blocking call.
        _redis = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=settings.worker_poll_timeout + 10,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
