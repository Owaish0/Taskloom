from fastapi import APIRouter, HTTPException, Request

from taskloom.models import TaskCreate, TaskRecord, TaskStatus
from taskloom.queue import create_task, get_task, list_tasks

router = APIRouter(prefix="/api/v1", tags=["tasks"])

SUPPORTED_TASK_TYPES = {"sleep"}


@router.post("/tasks", response_model=TaskRecord, status_code=201)
async def submit_task(task: TaskCreate, request: Request) -> TaskRecord:
    if task.type not in SUPPORTED_TASK_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported task type: {task.type!r}")

    if task.type == "sleep":
        duration = task.payload.get("duration")
        if not isinstance(duration, (int, float)) or duration <= 0:
            raise HTTPException(
                status_code=422, detail="payload.duration must be a positive number"
            )

    redis = request.app.state.redis
    return await create_task(redis, task.type, task.payload)


@router.get("/tasks/{task_id}", response_model=TaskRecord)
async def read_task(task_id: str, request: Request) -> TaskRecord:
    redis = request.app.state.redis
    record = await get_task(redis, task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return record


@router.get("/tasks", response_model=list[TaskRecord])
async def read_tasks(
    request: Request,
    status: TaskStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TaskRecord]:
    redis = request.app.state.redis
    return await list_tasks(redis, status=status, limit=limit, offset=offset)


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    redis = request.app.state.redis
    try:
        await redis.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}") from exc
    return {"status": "ok"}
