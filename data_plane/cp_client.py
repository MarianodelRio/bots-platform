import asyncio

import httpx


async def pull_tenant_config(cp_url: str, tenant_id: str, boot_token: str) -> dict:
    for attempt in range(5):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{cp_url}/tenant/{tenant_id}/config",
                    headers={"Authorization": f"Bearer {boot_token}"},
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError:
            raise
        except httpx.HTTPError:
            if attempt == 4:
                raise
            await asyncio.sleep(2 ** attempt)
    raise RuntimeError("unreachable")
