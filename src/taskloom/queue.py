from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from taskloom.models import TaskRecord, TaskStatus

PENDING_QUEUE = "queue:pending"
TASK_INDEX = "tasks:index"


def _task_key(task_id: str) -> str:
    return f"task:{task_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encode(record: TaskRecord) -> dict[str, str]:
    return {
        "id": record.id,
        "type": record.type,
        "status": record.status.value,
        "payload": json.dumps(record.payload),
        "result": json.dumps(record.result) if record.result is not None else "",
        "error": record.error or "",
        "attempts": str(record.attempts),
        "max_attempts": str(record.max_attempts),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _decode(data: dict[str, str]) -> TaskRecord:
    return TaskRecord(
        id=data["id"],
        type=data["type"],
        status=TaskStatus(data["status"]),
        payload=json.loads(data["payload"]) if data.get("payload") else {},
        result=json.loads(data["result"]) if data.get("result") else None,
        error=data.get("error") or None,
        attempts=int(data.get("attempts", 0)),
        max_attempts=int(data.get("max_attempts", 1)),
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


async def create_task(redis: Redis, task_type: str, payload: dict[str, Any]) -> TaskRecord:
    now = _now()
    record = TaskRecord(
        id=str(uuid.uuid4()),
        type=task_type,
        status=TaskStatus.PENDING,
        payload=payload,
        created_at=now,
        updated_at=now,
    )
    async with redis.pipeline(transaction=True) as pipe:
        pipe.hset(_task_key(record.id), mapping=_encode(record))
        pipe.zadd(TASK_INDEX, {record.id: time.time()})
        pipe.rpush(PENDING_QUEUE, record.id)
        await pipe.execute()
    return record


async def get_task(redis: Redis, task_id: str) -> TaskRecord | None:
    data = await redis.hgetall(_task_key(task_id))
    if not data:
        return None
    return _decode(data)


async def list_tasks(
    redis: Redis,
    status: TaskStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TaskRecord]:
    ids = await redis.zrevrange(TASK_INDEX, 0, -1)
    tasks: list[TaskRecord] = []
    for task_id in ids:
        record = await get_task(redis, task_id)
        if record is None:
            continue
        if status is not None and record.status != status:
            continue
        tasks.append(record)
    return tasks[offset : offset + limit]


async def set_status(
    redis: Redis,
    task_id: str,
    status: TaskStatus,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    fields: dict[str, str] = {"status": status.value, "updated_at": _now()}
    if result is not None:
        fields["result"] = json.dumps(result)
    if error is not None:
        fields["error"] = error
    await redis.hset(_task_key(task_id), mapping=fields)


async def dequeue(redis: Redis, timeout: int) -> str | None:
    item = await redis.blpop([PENDING_QUEUE], timeout=timeout)
    if item is None:
        return None
    _, task_id = item
    return task_id
