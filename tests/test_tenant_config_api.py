"""Integration tests for the Tenant Config API endpoint.

Uses in-memory SQLite via aiosqlite and overrides the get_db FastAPI dependency.
Run after `uv sync` to ensure all new dependencies are installed.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid

# Pin anyio to asyncio backend for all tests in this module.
anyio_backend = "asyncio"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select as sa_select  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Set ENCRYPTION_KEY before importing anything that calls _load_key() at module level.
_TEST_FERNET_KEY = "0gdkyDyOo3ekqTfcIBh3kdV1frqMM_ND1XjV4G8EYow="
os.environ.setdefault("ENCRYPTION_KEY", _TEST_FERNET_KEY)

# Also ensure DATABASE_URL resolves to SQLite so the engine created in database.py
# does not attempt a Postgres connection during import.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")

from control_plane.database import get_db  # noqa: E402
from control_plane.main import app  # noqa: E402
from control_plane.models import (  # noqa: E402
    Base,
    ChannelBinding,
    ConnectorBinding,
    Tenant,
    TenantCredential,
)
from control_plane.services.encryption import encrypt  # noqa: E402

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
# Seed helpers
# ---------------------------------------------------------------------------

_TENANT_ID = "peluqueria_sur"
_BOOT_TOKEN = "testtoken"
_TOKEN_HASH = hashlib.sha256(_BOOT_TOKEN.encode()).hexdigest()

_TENANT2_ID = "otra_tienda"
_BOOT_TOKEN2 = "othertoken"
_TOKEN_HASH2 = hashlib.sha256(_BOOT_TOKEN2.encode()).hexdigest()


async def _seed(session: AsyncSession) -> None:
    # Primary tenant
    tenant = Tenant(
        id=_TENANT_ID,
        name="Peluqueria Sur",
        status="active",
        flow_path="/app/flows/peluqueria.yaml",
        boot_token_hash=_TOKEN_HASH,
    )
    session.add(tenant)

    channel = ChannelBinding(
        id=str(uuid.uuid4()),
        tenant_id=_TENANT_ID,
        channel_type="whatsapp",
        channel_identifier="+34600000000",
    )
    session.add(channel)

    cred_payload = json.dumps({"project_id": "test-project", "type": "service_account"})
    cred = TenantCredential(
        id=str(uuid.uuid4()),
        tenant_id=_TENANT_ID,
        credential_type="calendar",
        encrypted_payload=encrypt(cred_payload),
    )
    session.add(cred)

    connector = ConnectorBinding(
        id=str(uuid.uuid4()),
        tenant_id=_TENANT_ID,
        category="calendar",
        adapter_type="google_calendar",
        config_json={"calendar_id": "primary", "timezone": "Europe/Madrid"},
    )
    session.add(connector)

    # Second tenant (for isolation testing)
    tenant2 = Tenant(
        id=_TENANT2_ID,
        name="Otra Tienda",
        status="active",
        flow_path="/app/flows/otra.yaml",
        boot_token_hash=_TOKEN_HASH2,
    )
    session.add(tenant2)

    channel2 = ChannelBinding(
        id=str(uuid.uuid4()),
        tenant_id=_TENANT2_ID,
        channel_type="whatsapp",
        channel_identifier="+34700000000",
    )
    session.add(channel2)

    await session.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
async def _setup_db():
    """Create tables and seed data before each test; drop after."""
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
async def test_get_config_success(client: AsyncClient):
    response = await client.get(
        f"/tenant/{_TENANT_ID}/config",
        headers={"Authorization": f"Bearer {_BOOT_TOKEN}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == _TENANT_ID
    assert "flow_path" in body
    assert "channel" in body
    assert "connectors" in body


@pytest.mark.anyio
async def test_get_config_wrong_token(client: AsyncClient):
    response = await client.get(
        f"/tenant/{_TENANT_ID}/config",
        headers={"Authorization": "Bearer wrongtoken"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


@pytest.mark.anyio
async def test_get_config_suspended_tenant(client: AsyncClient):
    # Suspend the tenant directly via a session
    async with _TestSessionLocal() as session:
        result = await session.execute(
            sa_select(Tenant).where(Tenant.id == _TENANT_ID)
        )
        tenant = result.scalar_one()
        tenant.status = "suspended"
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get(
            f"/tenant/{_TENANT_ID}/config",
            headers={"Authorization": f"Bearer {_BOOT_TOKEN}"},
        )
    assert response.status_code == 403
    assert response.json()["detail"] == "tenant_suspended"


@pytest.mark.anyio
async def test_get_config_unknown_tenant(client: AsyncClient):
    response = await client.get(
        "/tenant/does_not_exist/config",
        headers={"Authorization": "Bearer sometoken"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "tenant_not_found"


@pytest.mark.anyio
async def test_get_config_no_channel_binding(client: AsyncClient):
    # Add a tenant with no channel binding
    no_channel_token = "nochanneltoken"
    no_channel_hash = hashlib.sha256(no_channel_token.encode()).hexdigest()
    async with _TestSessionLocal() as session:
        tenant_nc = Tenant(
            id="no_channel_tenant",
            name="No Channel",
            status="active",
            flow_path="/app/flows/test.yaml",
            boot_token_hash=no_channel_hash,
        )
        session.add(tenant_nc)
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get(
            "/tenant/no_channel_tenant/config",
            headers={"Authorization": f"Bearer {no_channel_token}"},
        )
    assert response.status_code == 404
    assert response.json()["detail"] == "no_channel_binding"
