import hashlib
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane.database import get_db
from control_plane.models import Tenant
from control_plane.services.tenant_config_service import get_tenant_boot_config

router = APIRouter()


@router.get("/tenant/{tenant_id}/config")
async def get_config(
    tenant_id: str,
    authorization: str = Header(...),
    session: AsyncSession = Depends(get_db),
):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="invalid_token")
    token = authorization.removeprefix("Bearer ")

    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant_not_found")

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    if not hmac.compare_digest(token_hash, tenant.boot_token_hash):
        raise HTTPException(status_code=401, detail="invalid_token")

    if tenant.status != "active":
        raise HTTPException(status_code=403, detail="tenant_suspended")

    try:
        config = await get_tenant_boot_config(tenant_id, session)
    except ValueError as e:
        if str(e) == "no_channel_binding":
            raise HTTPException(status_code=404, detail="no_channel_binding")
        raise

    if config is None:
        raise HTTPException(status_code=404, detail="tenant_not_found")

    return config
