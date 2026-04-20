from typing import Any

import httpx


class SearxngClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def search(self, query: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}/search", params={"q": query, "format": "json"})
            response.raise_for_status()
            payload = response.json()
        return payload.get("results", [])
