import httpx


async def pull_tenant_config(cp_url: str, tenant_id: str, boot_token: str) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{cp_url}/tenant/{tenant_id}/config",
            headers={"Authorization": f"Bearer {boot_token}"},
        )
        response.raise_for_status()
        return response.json()
