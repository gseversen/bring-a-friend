from urllib.parse import quote

import httpx2


class SyncClient:
    """Sends agent messages to the sync server, which writes them into the room's Yjs doc."""

    def __init__(self, base_url: str):
        self._http = httpx2.AsyncClient(base_url=base_url, timeout=5.0)

    async def send(self, room: str, message: dict) -> None:
        response = await self._http.post(f"/rooms/{quote(room, safe='')}/messages", json=message)
        response.raise_for_status()

    async def aclose(self) -> None:
        await self._http.aclose()
