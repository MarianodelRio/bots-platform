import asyncio
import os
from contextlib import asynccontextmanager

import alembic.command
import alembic.config
from fastapi import FastAPI

from control_plane.routers.flows import router as flows_router
from control_plane.routers.tenant_config import router as tenant_config_router


def _run_migrations() -> None:
    db_url = os.environ["DATABASE_URL"]
    # Convert async driver URLs to sync driver URLs for Alembic
    db_url = db_url.replace("+asyncpg", "+psycopg2")
    db_url = db_url.replace("+aiosqlite", "")
    cfg = alembic.config.Config("control_plane/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    alembic.command.upgrade(cfg, "head")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await asyncio.to_thread(_run_migrations)
    yield


app = FastAPI(lifespan=_lifespan)
app.include_router(tenant_config_router)
app.include_router(flows_router, prefix="")


@app.get("/health")
def health():
    return {"status": "ok"}
