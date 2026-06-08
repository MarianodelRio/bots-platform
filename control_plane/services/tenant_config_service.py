import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane.models import ChannelBinding, ConnectorBinding, Tenant, TenantCredential
from control_plane.services.encryption import decrypt


async def get_tenant_boot_config(tenant_id: str, session: AsyncSession) -> dict | None:
    # Fetch tenant
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        return None

    # Fetch channel bindings
    cb_result = await session.execute(
        select(ChannelBinding).where(ChannelBinding.tenant_id == tenant_id)
    )
    channels = cb_result.scalars().all()
    if not channels:
        raise ValueError("no_channel_binding")

    # Fetch credentials
    cred_result = await session.execute(
        select(TenantCredential).where(TenantCredential.tenant_id == tenant_id)
    )
    credentials = {
        c.credential_type: json.loads(decrypt(c.encrypted_payload))
        for c in cred_result.scalars().all()
    }

    # Fetch connector bindings
    conn_result = await session.execute(
        select(ConnectorBinding).where(ConnectorBinding.tenant_id == tenant_id)
    )
    connectors = {}
    for cb in conn_result.scalars().all():
        cfg = dict(cb.config_json) if cb.config_json else {}
        cfg["type"] = cb.adapter_type
        # Merge credentials for this category
        if cb.category in credentials:
            cfg["credentials_dict"] = credentials[cb.category]
        connectors[cb.category] = cfg

    # Use first channel binding as the primary channel
    ch = channels[0]

    ch_dict: dict = {
        "type": ch.channel_type,
        "identifier": ch.channel_identifier,
    }
    # WhatsApp credential JSON must use keys: access_token, app_secret, verify_token
    whatsapp_creds: dict = credentials.get("whatsapp", {})
    if whatsapp_creds:
        ch_dict["access_token"] = whatsapp_creds.get("access_token")
        ch_dict["app_secret"] = whatsapp_creds.get("app_secret")
        ch_dict["verify_token"] = whatsapp_creds.get("verify_token")

    return {
        "tenant_id": tenant_id,
        "flow_path": tenant.flow_path,
        "channel": ch_dict,
        "connectors": connectors,
    }
