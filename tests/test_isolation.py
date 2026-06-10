"""F8 isolation tests — verifies conversation state and boot tokens are fully
isolated between peluqueria_sur and peluqueria_norte tenants.

Layer 1 (async, anyio): CP token cross-tenant rejection/acceptance via the
                         FastAPI test client.
Layer 2 (sync):          SQLiteStateStore is keyed by tenant_id so writes for
                         tenant A are invisible to tenant B.
Layer 3 (sync):          Two Bot instances with separate stores have no bleed.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime
from pathlib import Path

anyio_backend = "asyncio"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Ensure env vars are set before importing anything that reads them at module level.
_TEST_FERNET_KEY = "0gdkyDyOo3ekqTfcIBh3kdV1frqMM_ND1XjV4G8EYow="
os.environ.setdefault("ENCRYPTION_KEY", _TEST_FERNET_KEY)
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from control_plane.database import get_db  # noqa: E402
from control_plane.main import app  # noqa: E402
from control_plane.models import Base, ChannelBinding, Flow, FlowVersion, Tenant  # noqa: E402
from data_plane.adapters.connectors.mock import MockConnector  # noqa: E402
from data_plane.adapters.state_store.sqlite import SQLiteStateStore  # noqa: E402
from data_plane.engine.bot import Bot  # noqa: E402
from data_plane.engine.flow import load_flow  # noqa: E402
from data_plane.engine.outputs import SendInteractiveButtonsOutput  # noqa: E402
from shared.domain.conversation import ConversationState  # noqa: E402
from shared.domain.messages import InternalMessage, MessageType  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_FLOWS_DIR = Path(__file__).parent.parent / "flows"
_SUR_FLOW_PATH = _FLOWS_DIR / "peluqueria_flow.yaml"
_NORTE_FLOW_PATH = _FLOWS_DIR / "peluqueria_norte_flow.yaml"

# ---------------------------------------------------------------------------
# Token / hash constants
# ---------------------------------------------------------------------------

_SUR_TOKEN = "sur-boot-2024"
_SUR_HASH = hashlib.sha256(_SUR_TOKEN.encode()).hexdigest()

_NORTE_TOKEN = "norte-boot-2024"
_NORTE_HASH = hashlib.sha256(_NORTE_TOKEN.encode()).hexdigest()

# ---------------------------------------------------------------------------
# Layer 1 — CP token cross-tenant (async, anyio)
# ---------------------------------------------------------------------------

_TEST_DB_URL = "sqlite+aiosqlite:///"

_test_engine = create_async_engine(_TEST_DB_URL, connect_args={"check_same_thread": False})
_TestSession: async_sessionmaker[AsyncSession] = async_sessionmaker(
    _test_engine, expire_on_commit=False
)


async def _override_get_db():
    async with _TestSession() as session:
        yield session


async def _seed_cp(session: AsyncSession) -> None:
    yaml_sur = _SUR_FLOW_PATH.read_text()
    yaml_norte = _NORTE_FLOW_PATH.read_text()

    for tenant_id, name, token_hash, channel_id, yaml_content in [
        ("peluqueria_sur",   "Peluquería Sur",   _SUR_HASH,   "sur",   yaml_sur),
        ("peluqueria_norte", "Peluquería Norte", _NORTE_HASH, "norte", yaml_norte),
    ]:
        tenant = Tenant(
            id=tenant_id,
            name=name,
            status="active",
            boot_token_hash=token_hash,
        )
        session.add(tenant)

        binding = ChannelBinding(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            channel_type="http_dev",
            channel_identifier=channel_id,
        )
        session.add(binding)

        # Active flow version so /config returns 200
        checksum = hashlib.sha256(yaml_content.encode()).hexdigest()
        flow = Flow(id=str(uuid.uuid4()), tenant_id=tenant_id, name="peluqueria")
        session.add(flow)
        await session.flush()

        fv = FlowVersion(
            id=str(uuid.uuid4()),
            flow_id=flow.id,
            version=1,
            yaml_content=yaml_content,
            checksum=checksum,
            is_active=True,
        )
        session.add(fv)

    await session.commit()


@pytest.fixture
async def seeded_client():
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with _TestSession() as session:
        await _seed_cp(session)

    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_db, None)

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.anyio
async def test_sur_token_rejected_on_norte(seeded_client: AsyncClient):
    response = await seeded_client.get(
        "/tenant/peluqueria_norte/config",
        headers={"Authorization": f"Bearer {_SUR_TOKEN}"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


@pytest.mark.anyio
async def test_norte_token_rejected_on_sur(seeded_client: AsyncClient):
    response = await seeded_client.get(
        "/tenant/peluqueria_sur/config",
        headers={"Authorization": f"Bearer {_NORTE_TOKEN}"},
    )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_sur_token_accepted_on_sur(seeded_client: AsyncClient):
    response = await seeded_client.get(
        "/tenant/peluqueria_sur/config",
        headers={"Authorization": f"Bearer {_SUR_TOKEN}"},
    )
    assert response.status_code == 200


@pytest.mark.anyio
async def test_norte_token_accepted_on_norte(seeded_client: AsyncClient):
    response = await seeded_client.get(
        "/tenant/peluqueria_norte/config",
        headers={"Authorization": f"Bearer {_NORTE_TOKEN}"},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Helpers for Layer 2 & 3
# ---------------------------------------------------------------------------

def _make_msg(tenant_id: str, contact_id: str, payload: str) -> InternalMessage:
    return InternalMessage(
        tenant_id=tenant_id,
        contact_id=contact_id,
        message_type=MessageType.BUTTON_REPLY,
        text=None,
        payload=payload,
        timestamp=datetime.utcnow(),
    )


def _make_bot(flow_path: Path, store: SQLiteStateStore) -> Bot:
    flow = load_flow(flow_path.read_text())
    connector = MockConnector()
    return Bot(flow=flow, state_store=store, connector=connector)


# ---------------------------------------------------------------------------
# Layer 2 — SQLiteStateStore isolation (sync)
# ---------------------------------------------------------------------------

def test_state_is_keyed_by_tenant_id(tmp_path):
    store = SQLiteStateStore(str(tmp_path / "state.db"))
    state = ConversationState(
        tenant_id="peluqueria_sur",
        contact_id="alice",
        current_state="BOOK_SELECT_SERVICE",
        data={},
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    store.save(state)
    # A state saved for sur must not be visible under norte for the same contact.
    assert store.get("peluqueria_norte", "alice") is None


def test_same_store_two_tenants_no_bleed(tmp_path):
    store = SQLiteStateStore(str(tmp_path / "state.db"))

    bot_sur = _make_bot(_SUR_FLOW_PATH, store)

    # Advance alice in bot_sur from MENU to BOOK_SELECT_SERVICE via menu_book.
    msg = _make_msg("peluqueria_sur", "alice", "menu_book")
    bot_sur.handle_message(msg)

    # alice should now be in BOOK_SELECT_SERVICE for sur.
    sur_state = store.get("peluqueria_sur", "alice")
    assert sur_state is not None
    assert sur_state.current_state == "BOOK_SELECT_SERVICE"

    # norte side must be completely empty — no bleed from shared store.
    assert store.get("peluqueria_norte", "alice") is None


# ---------------------------------------------------------------------------
# Layer 3 — Two Bot instances with separate stores (sync)
# ---------------------------------------------------------------------------

def test_two_dp_instances_separate_stores(tmp_path):
    store_sur = SQLiteStateStore(str(tmp_path / "sur.db"))
    store_norte = SQLiteStateStore(str(tmp_path / "norte.db"))

    bot_sur = _make_bot(_SUR_FLOW_PATH, store_sur)
    bot_norte = _make_bot(_NORTE_FLOW_PATH, store_norte)

    # Advance alice in both bots to BOOK_SELECT_SERVICE.
    bot_sur.handle_message(_make_msg("peluqueria_sur", "alice", "menu_book"))
    bot_norte.handle_message(_make_msg("peluqueria_norte", "alice", "menu_book"))

    sur_state = store_sur.get("peluqueria_sur", "alice")
    norte_state = store_norte.get("peluqueria_norte", "alice")

    assert sur_state is not None and sur_state.current_state == "BOOK_SELECT_SERVICE"
    assert norte_state is not None and norte_state.current_state == "BOOK_SELECT_SERVICE"

    # Cross-store: each store is ignorant of the other tenant.
    assert store_sur.get("peluqueria_norte", "alice") is None
    assert store_norte.get("peluqueria_sur", "alice") is None


def test_contact_advances_sur_only(tmp_path):
    store_sur = SQLiteStateStore(str(tmp_path / "sur.db"))
    store_norte = SQLiteStateStore(str(tmp_path / "norte.db"))

    bot_sur = _make_bot(_SUR_FLOW_PATH, store_sur)
    bot_norte = _make_bot(_NORTE_FLOW_PATH, store_norte)

    # Advance alice in bot_sur to BOOK_SELECT_SERVICE.
    bot_sur.handle_message(_make_msg("peluqueria_sur", "alice", "menu_book"))

    sur_state = store_sur.get("peluqueria_sur", "alice")
    assert sur_state is not None and sur_state.current_state == "BOOK_SELECT_SERVICE"

    # Send alice's first message to bot_norte using an unrecognised payload so
    # the MENU fallback fires and re-runs MENU on_enter, emitting the norte greeting.
    outputs = bot_norte.handle_message(_make_msg("peluqueria_norte", "alice", "unknown_payload"))

    # norte should respond with its own MENU greeting (Peluquería Norte copy).
    assert len(outputs) > 0
    first = outputs[0]
    assert isinstance(first, SendInteractiveButtonsOutput)
    assert "Norte" in first.body

    # norte state remains at MENU (fallback kept her there).
    norte_state = store_norte.get("peluqueria_norte", "alice")
    assert norte_state is not None
    assert norte_state.current_state == "MENU"
    # Crucially, norte_state was created fresh — not copied from sur.
    assert store_sur.get("peluqueria_norte", "alice") is None
