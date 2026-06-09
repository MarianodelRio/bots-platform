import hashlib
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane.database import get_db
from control_plane.models import Flow, FlowVersion
from control_plane.services.flow_validator import validate_flow_yaml

router = APIRouter()


def _check_admin_key(x_admin_key: str | None = Header(default=None)) -> None:
    expected = os.environ["ADMIN_API_KEY"]
    if x_admin_key is None:
        raise HTTPException(status_code=401, detail="missing admin key")
    if x_admin_key != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


class FlowUploadBody(BaseModel):
    yaml_content: str
    name: str


@router.post("/tenants/{tenant_id}/flows", status_code=201)
async def upload_flow(
    tenant_id: str,
    body: FlowUploadBody,
    _: None = Depends(_check_admin_key),
    session: AsyncSession = Depends(get_db),
):
    errors = validate_flow_yaml(body.yaml_content)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})

    # Fetch or create Flow for tenant
    result = await session.execute(select(Flow).where(Flow.tenant_id == tenant_id))
    flow = result.scalar_one_or_none()
    if flow is None:
        flow = Flow(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=body.name,
        )
        session.add(flow)
        await session.flush()

    # Compute next version number
    max_result = await session.execute(
        select(func.max(FlowVersion.version)).where(FlowVersion.flow_id == flow.id)
    )
    max_version = max_result.scalar()
    next_version = 1 if max_version is None else max_version + 1

    checksum = hashlib.sha256(body.yaml_content.encode()).hexdigest()
    flow_version = FlowVersion(
        id=str(uuid.uuid4()),
        flow_id=flow.id,
        version=next_version,
        yaml_content=body.yaml_content,
        checksum=checksum,
        is_active=False,
    )
    session.add(flow_version)
    await session.commit()

    return {"flow_id": flow.id, "version": next_version, "checksum": checksum}


@router.put("/tenants/{tenant_id}/flows/activate/{version}", status_code=200)
async def activate_flow_version(
    tenant_id: str,
    version: int,
    _: None = Depends(_check_admin_key),
    session: AsyncSession = Depends(get_db),
):
    # Fetch Flow for tenant
    result = await session.execute(select(Flow).where(Flow.tenant_id == tenant_id))
    flow = result.scalar_one_or_none()
    if flow is None:
        raise HTTPException(status_code=404, detail="flow_not_found")

    # Fetch requested FlowVersion
    fv_result = await session.execute(
        select(FlowVersion).where(
            FlowVersion.flow_id == flow.id,
            FlowVersion.version == version,
        )
    )
    flow_version = fv_result.scalar_one_or_none()
    if flow_version is None:
        raise HTTPException(status_code=404, detail="version_not_found")

    # Deactivate previously active version
    prev_result = await session.execute(
        select(FlowVersion).where(
            FlowVersion.flow_id == flow.id,
            FlowVersion.is_active == True,  # noqa: E712
        )
    )
    prev_active = prev_result.scalar_one_or_none()
    if prev_active is not None:
        prev_active.is_active = False

    flow_version.is_active = True
    await session.commit()

    return {
        "flow_id": flow.id,
        "version": version,
        "activated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/tenants/{tenant_id}/flows/active", status_code=200)
async def get_active_flow(
    tenant_id: str,
    _: None = Depends(_check_admin_key),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(Flow).where(Flow.tenant_id == tenant_id))
    flow = result.scalar_one_or_none()
    if flow is None:
        raise HTTPException(status_code=404, detail="flow_not_found")

    fv_result = await session.execute(
        select(FlowVersion).where(
            FlowVersion.flow_id == flow.id,
            FlowVersion.is_active == True,  # noqa: E712
        )
    )
    flow_version = fv_result.scalar_one_or_none()
    if flow_version is None:
        raise HTTPException(status_code=404, detail="no_active_version")

    return {
        "version": flow_version.version,
        "yaml_content": flow_version.yaml_content,
        "checksum": flow_version.checksum,
        "created_at": flow_version.created_at.isoformat() if flow_version.created_at else None,
    }


@router.get("/tenants/{tenant_id}/flows/versions", status_code=200)
async def list_flow_versions(
    tenant_id: str,
    _: None = Depends(_check_admin_key),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(Flow).where(Flow.tenant_id == tenant_id))
    flow = result.scalar_one_or_none()
    if flow is None:
        return []

    fv_result = await session.execute(
        select(FlowVersion).where(FlowVersion.flow_id == flow.id)
    )
    versions = fv_result.scalars().all()
    return [
        {
            "version": fv.version,
            "is_active": fv.is_active,
            "checksum": fv.checksum,
            "created_at": fv.created_at.isoformat() if fv.created_at else None,
        }
        for fv in versions
    ]
