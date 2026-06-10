"""Idempotent seed script for F8 multi-tenancy.

Registers peluqueria_sur and peluqueria_norte tenants with their boot tokens,
channel bindings, and active flow versions.

Usage:
    uv run python scripts/seed_f8.py
"""

from __future__ import annotations

import hashlib
import os
import uuid

import httpx
import psycopg2

TENANTS = [
    {"id": "peluqueria_sur", "name": "Peluquería Sur", "token": "sur-boot-2024", "binding": "sur"},
    {
        "id": "peluqueria_norte",
        "name": "Peluquería Norte",
        "token": "norte-boot-2024",
        "binding": "norte",
    },
]

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
_raw_db_url = os.environ["DATABASE_URL"]
# Strip async driver suffix so psycopg2 can use the URL directly.
DATABASE_URL = _raw_db_url.replace("+asyncpg", "").replace("+aiosqlite", "")

ADMIN_API_KEY = os.environ["ADMIN_API_KEY"]
CONTROL_PLANE_URL = os.environ.get("CONTROL_PLANE_URL", "http://localhost:8001")


# ---------------------------------------------------------------------------
# Step A — SQL via psycopg2 (sync)
# ---------------------------------------------------------------------------
def seed_db() -> None:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    for t in TENANTS:
        token_hash = hashlib.sha256(t["token"].encode()).hexdigest()
        cur.execute(
            "INSERT INTO tenants (id, name, boot_token_hash, status, created_at) "
            "VALUES (%s, %s, %s, %s, NOW()) "
            "ON CONFLICT (id) DO UPDATE SET "
            "name=EXCLUDED.name, boot_token_hash=EXCLUDED.boot_token_hash",
            (t["id"], t["name"], token_hash, "active"),
        )
        print(f"[db] upserted tenant {t['id']}")

        cur.execute("DELETE FROM channel_bindings WHERE tenant_id = %s", (t["id"],))
        cur.execute(
            "INSERT INTO channel_bindings "
            "(id, tenant_id, channel_type, channel_identifier, created_at) "
            "VALUES (%s, %s, %s, %s, NOW())",
            (str(uuid.uuid4()), t["id"], "http_dev", t["binding"]),
        )
        print(f"[db] channel_binding set for {t['id']} -> {t['binding']}")

    conn.commit()
    cur.close()
    conn.close()
    print("[db] done")


# ---------------------------------------------------------------------------
# Step B — CP API via httpx (sync)
# ---------------------------------------------------------------------------
def seed_flows() -> None:
    with httpx.Client(
        base_url=CONTROL_PLANE_URL,
        headers={"X-Admin-Key": ADMIN_API_KEY},
        timeout=30.0,
    ) as client:
        for t in TENANTS:
            r = client.get(f"/tenants/{t['id']}/flows/versions")
            r.raise_for_status()
            versions = r.json()

            if any(v["is_active"] for v in versions):
                print(f"[skip] {t['id']} already has an active flow version")
                continue

            if not versions:
                yaml_path = (
                    "flows/peluqueria_norte_flow.yaml"
                    if "norte" in t["id"]
                    else "flows/peluqueria_flow.yaml"
                )
                yaml_content = open(yaml_path).read()
                resp_create = client.post(
                    f"/tenants/{t['id']}/flows",
                    json={"name": "peluqueria", "yaml_content": yaml_content},
                )
                resp_create.raise_for_status()
                print(f"[api] flow version created for {t['id']}: {resp_create.json()}")
                version_to_activate = 1
            else:
                version_to_activate = max(v["version"] for v in versions)
                print(
                    f"[api] found inactive version {version_to_activate}"
                    f" for {t['id']}, will activate"
                )

            resp_activate = client.put(f"/tenants/{t['id']}/flows/activate/{version_to_activate}")
            resp_activate.raise_for_status()
            print(f"[api] flow version {version_to_activate} activated for {t['id']}")

            print(f"[seeded] {t['id']}")


if __name__ == "__main__":
    seed_db()
    seed_flows()
    print("[seed_f8] complete")
