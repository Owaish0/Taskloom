from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

HandlerFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


async def sleep_handler(payload: dict[str, Any]) -> dict[str, Any]:
    duration = float(payload["duration"])
    await asyncio.sleep(duration)
    return {"slept_for": duration}


HANDLERS: dict[str, HandlerFn] = {
    "sleep": sleep_handler,
}
