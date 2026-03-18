import httpx


class VestaboardClient:
    def __init__(self, token: str, api_url: str = "https://rw.vestaboard.com/"):
        self.token = token
        self.api_url = api_url.rstrip("/") + "/"

    def _headers(self) -> dict:
        return {
            "X-Vestaboard-Read-Write-Key": self.token,
            "Content-Type": "application/json",
        }

    async def send(self, text: str) -> dict:
        """Send plain text to the board. The API auto-formats it for the 15×3 Note layout."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                self.api_url,
                headers=self._headers(),
                json={"text": text},
            )
            r.raise_for_status()
            return r.json()

    async def send_characters(self, rows: list[list[int]]) -> dict:
        """Send a raw 3×15 character-code array to the board."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                self.api_url,
                headers=self._headers(),
                json={"characters": rows},
            )
            r.raise_for_status()
            return r.json()

    async def read(self) -> dict:
        """Read the current message on the board."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(self.api_url, headers=self._headers())
            r.raise_for_status()
            return r.json()
