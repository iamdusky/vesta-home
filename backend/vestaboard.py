import httpx

# Character code map for converting plain text → local API char arrays
_CHAR_MAP: dict[str, int] = {
    " ": 0,
    **{chr(ord("A") + i): i + 1 for i in range(26)},   # A-Z → 1-26
    **{str(i): i + 27 for i in range(10)},              # 0-9 → 27-36
    "!": 37, '"': 38, "#": 39, "$": 40, "%": 41, "&": 42,
    "'": 43, "(": 44, ")": 45, "*": 46, "+": 47, ",": 48,
    "-": 49, ".": 50, "/": 51, ":": 52, ";": 53, "<": 54,
    "=": 55, ">": 56, "?": 57, "@": 58,
}


def _text_to_chars(text: str) -> list[list[int]]:
    """Convert newline-separated text into a 3×15 character-code array."""
    lines = (text.upper() + "\n\n").split("\n")[:3]
    rows = []
    for line in lines:
        row = [_CHAR_MAP.get(ch, 0) for ch in line[:15]]
        row += [0] * (15 - len(row))
        rows.append(row)
    return rows


class VestaboardClient:
    def __init__(self, token: str, api_url: str = "https://rw.vestaboard.com/"):
        self.token   = token
        self.api_url = api_url.rstrip("/") + "/"
        self.local   = "/local-api/" in self.api_url

    def _headers(self) -> dict:
        key = "X-Vestaboard-Local-Api-Key" if self.local else "X-Vestaboard-Read-Write-Key"
        return {key: self.token, "Content-Type": "application/json"}

    async def send(self, text: str) -> dict:
        """Send plain text to the board."""
        if self.local:
            # Local API has no text endpoint — convert to character codes
            return await self.send_characters(_text_to_chars(text))
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(self.api_url, headers=self._headers(), json={"text": text})
            r.raise_for_status()
            return r.json() if r.content else {}

    async def send_characters(self, rows: list[list[int]],
                              strategy: str | None = None,
                              step_interval_ms: int = 200,
                              step_size: int = 1) -> dict:
        """Send a raw 3×15 character-code array to the board.

        Local API supports animation strategies:
          column, reverse-column, edges-to-center, row, diagonal, random
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            if self.local:
                if strategy:
                    body = {
                        "characters": rows,
                        "strategy": strategy,
                        "step_interval_ms": step_interval_ms,
                        "step_size": step_size,
                    }
                else:
                    body = rows   # bare array — simplest local send
            else:
                body = {"characters": rows}
            r = await client.post(self.api_url, headers=self._headers(), json=body)
            r.raise_for_status()
            return r.json() if r.content else {}

    async def read(self) -> dict:
        """Read the current message on the board."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(self.api_url, headers=self._headers())
            r.raise_for_status()
            return r.json()
