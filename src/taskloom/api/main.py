from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from taskloom.api.routers.status import router as status_router
from taskloom.api.routers.tasks import router as tasks_router
from taskloom.config import settings
from taskloom.redis_client import close_redis, get_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = get_redis()
    yield
    await close_redis()


app = FastAPI(title="Taskloom API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks_router)
app.include_router(status_router)
