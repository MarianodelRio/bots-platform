"""Integration tests for the Flow Authoring API endpoints."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

# Set env vars BEFORE importing anything that touches the app or models.
os.environ["ADMIN_API_KEY"] = "test-admin-key"
os.environ.setdefault("ENCRYPTION_KEY", "0gdkyDyOo3ekqTfcIBh3kdV1frqMM_ND1XjV4G8EYow=")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")

anyio_backend = "asyncio"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from control_plane.database import get_db  # noqa: E402
from control_plane.main import app  # noqa: E402
from control_plane.models import Base, Tenant  # noqa: E402

# ---------------------------------------------------------------------------
# Test database setup
# ---------------------------------------------------------------------------

_TEST_DB_URL = "sqlite+aiosqlite:///"

_test_engine = create_async_engine(
    _TEST_DB_URL,
    connect_args={"check_same_thread": False},
)
_TestSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    _test_engine, expire_on_commit=False
)


async def _override_get_db():
    async with _TestSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TENANT_ID = "peluqueria_sur"
_BOOT_TOKEN = "testtoken"
_TOKEN_HASH = hashlib.sha256(_BOOT_TOKEN.encode()).hexdigest()

_ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}
_WRONG_ADMIN_HEADERS = {"X-Admin-Key": "wrong-key"}

_PELUQUERIA_FLOW_PATH = Path(__file__).parent.parent / "flows" / "peluqueria_flow.yaml"
_PELUQUERIA_YAML = _PELUQUERIA_FLOW_PATH.read_text()

_INVALID_YAML_BODY = {
    "yaml_content": "initial_state: START\n",  # missing states key
    "name": "bad_flow",
}


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

async def _seed(session: AsyncSession) -> None:
    tenant = Tenant(
        id=_TENANT_ID,
        name="Peluqueria Sur",
        status="active",
        boot_token_hash=_TOKEN_HASH,
    )
    session.add(tenant)
    await session.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
async def _setup_db():
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with _TestSessionLocal() as session:
        await _seed(session)

    app.dependency_overrides[get_db] = _override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_post_valid_flow_returns_201(client: AsyncClient):
    response = await client.post(
        f"/tenants/{_TENANT_ID}/flows",
        json={"yaml_content": _PELUQUERIA_YAML, "name": "peluqueria"},
        headers=_ADMIN_HEADERS,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["version"] == 1
    assert "flow_id" in body
    assert "checksum" in body


@pytest.mark.anyio
async def test_post_invalid_yaml_returns_422(client: AsyncClient):
    response = await client.post(
        f"/tenants/{_TENANT_ID}/flows",
        json=_INVALID_YAML_BODY,
        headers=_ADMIN_HEADERS,
    )
    assert response.status_code == 422
    body = response.json()
    assert "errors" in body["detail"]
    assert len(body["detail"]["errors"]) > 0


@pytest.mark.anyio
async def test_post_second_version_increments(client: AsyncClient):
    # First upload
    await client.post(
        f"/tenants/{_TENANT_ID}/flows",
        json={"yaml_content": _PELUQUERIA_YAML, "name": "peluqueria"},
        headers=_ADMIN_HEADERS,
    )
    # Second upload
    response = await client.post(
        f"/tenants/{_TENANT_ID}/flows",
        json={"yaml_content": _PELUQUERIA_YAML, "name": "peluqueria"},
        headers=_ADMIN_HEADERS,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["version"] == 2


@pytest.mark.anyio
async def test_put_activate_version_1(client: AsyncClient):
    # Upload first
    post_resp = await client.post(
        f"/tenants/{_TENANT_ID}/flows",
        json={"yaml_content": _PELUQUERIA_YAML, "name": "peluqueria"},
        headers=_ADMIN_HEADERS,
    )
    assert post_resp.status_code == 201

    response = await client.put(
        f"/tenants/{_TENANT_ID}/flows/activate/1",
        headers=_ADMIN_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert "activated_at" in body


@pytest.mark.anyio
async def test_put_activate_nonexistent_version_returns_404(client: AsyncClient):
    # Upload a flow first so a Flow record exists
    await client.post(
        f"/tenants/{_TENANT_ID}/flows",
        json={"yaml_content": _PELUQUERIA_YAML, "name": "peluqueria"},
        headers=_ADMIN_HEADERS,
    )
    response = await client.put(
        f"/tenants/{_TENANT_ID}/flows/activate/99",
        headers=_ADMIN_HEADERS,
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_put_activate_no_flow_for_tenant_returns_404(client: AsyncClient):
    response = await client.put(
        "/tenants/nonexistent_tenant/flows/activate/1",
        headers=_ADMIN_HEADERS,
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_get_active_no_active_version_returns_404(client: AsyncClient):
    # Upload but do NOT activate
    await client.post(
        f"/tenants/{_TENANT_ID}/flows",
        json={"yaml_content": _PELUQUERIA_YAML, "name": "peluqueria"},
        headers=_ADMIN_HEADERS,
    )
    response = await client.get(
        f"/tenants/{_TENANT_ID}/flows/active",
        headers=_ADMIN_HEADERS,
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_get_active_after_activation_returns_200(client: AsyncClient):
    # Upload and activate
    await client.post(
        f"/tenants/{_TENANT_ID}/flows",
        json={"yaml_content": _PELUQUERIA_YAML, "name": "peluqueria"},
        headers=_ADMIN_HEADERS,
    )
    await client.put(
        f"/tenants/{_TENANT_ID}/flows/activate/1",
        headers=_ADMIN_HEADERS,
    )
    response = await client.get(
        f"/tenants/{_TENANT_ID}/flows/active",
        headers=_ADMIN_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert "yaml_content" in body
    assert "checksum" in body


@pytest.mark.anyio
async def test_get_versions_returns_correct_is_active_flags(client: AsyncClient):
    # Upload two versions
    await client.post(
        f"/tenants/{_TENANT_ID}/flows",
        json={"yaml_content": _PELUQUERIA_YAML, "name": "peluqueria"},
        headers=_ADMIN_HEADERS,
    )
    await client.post(
        f"/tenants/{_TENANT_ID}/flows",
        json={"yaml_content": _PELUQUERIA_YAML, "name": "peluqueria"},
        headers=_ADMIN_HEADERS,
    )
    # Activate version 2
    await client.put(
        f"/tenants/{_TENANT_ID}/flows/activate/2",
        headers=_ADMIN_HEADERS,
    )

    response = await client.get(
        f"/tenants/{_TENANT_ID}/flows/versions",
        headers=_ADMIN_HEADERS,
    )
    assert response.status_code == 200
    versions = response.json()
    assert len(versions) == 2
    versions_by_num = {v["version"]: v for v in versions}
    assert versions_by_num[1]["is_active"] is False
    assert versions_by_num[2]["is_active"] is True


@pytest.mark.anyio
async def test_request_without_admin_key_returns_401(client: AsyncClient):
    response = await client.post(
        f"/tenants/{_TENANT_ID}/flows",
        json={"yaml_content": _PELUQUERIA_YAML, "name": "peluqueria"},
    )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_request_with_wrong_admin_key_returns_401(client: AsyncClient):
    response = await client.post(
        f"/tenants/{_TENANT_ID}/flows",
        json={"yaml_content": _PELUQUERIA_YAML, "name": "peluqueria"},
        headers=_WRONG_ADMIN_HEADERS,
    )
    assert response.status_code == 401
