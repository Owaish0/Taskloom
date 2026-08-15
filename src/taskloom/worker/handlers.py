from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

HandlerFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


async def sleep_handler(payload: dict[str, Any]) -> dict[str, Any]:
    duration = float(payload["duration"])
    await asyncio.sleep(duration)
    return {"slept_for": duration}


async def fail_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """Always raises. Exists to exercise (and demo) the retry / dead-letter
    queue path without needing a real flaky dependency."""
    raise RuntimeError(payload.get("message", "task configured to always fail"))


HANDLERS: dict[str, HandlerFn] = {
    "sleep": sleep_handler,
    "fail": fail_handler,
}
