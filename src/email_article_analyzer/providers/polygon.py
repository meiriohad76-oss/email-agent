from typing import Protocol

import httpx


class PolygonTickerValidator(Protocol):
    def validate_ticker(self, ticker: str) -> dict | None:
        ...


class PolygonHttpClient:
    def __init__(self, api_key: str, base_url: str = "https://api.polygon.io"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def validate_ticker(self, ticker: str) -> dict | None:
        response = httpx.get(
            f"{self.base_url}/v3/reference/tickers/{ticker}",
            params={"apiKey": self.api_key},
            timeout=10,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        result = payload.get("results")
        if not result:
            return None
        return result
