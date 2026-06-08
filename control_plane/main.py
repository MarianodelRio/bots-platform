from contextlib import asynccontextmanager

from fastapi import FastAPI

from control_plane.database import engine
from control_plane.models import Base
from control_plane.routers.tenant_config import router as tenant_config_router


@asynccontextmanager
async def _lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(lifespan=_lifespan)
app.include_router(tenant_config_router)


@app.get("/health")
def health():
    return {"status": "ok"}
