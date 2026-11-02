from typing import Protocol

import certifi
import httpx
import os
from pathlib import Path
import ssl
import tempfile


class PolygonTickerValidator(Protocol):
    def validate_ticker(self, ticker: str) -> dict | None:
        ...


class PolygonHttpClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.polygon.io",
        http_get=None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.http_get = http_get or _certifi_http_get

    def validate_ticker(self, ticker: str) -> dict | None:
        response = self.http_get(
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

    def previous_close(self, ticker: str) -> dict | None:
        response = self.http_get(
            f"{self.base_url}/v2/aggs/ticker/{ticker}/prev",
            params={"apiKey": self.api_key, "adjusted": "true"},
            timeout=10,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results") or []
        if not results:
            return None
        result = results[0]
        close = result.get("c")
        if close is None:
            return None
        snapshot = {
            "ticker": ticker,
            "last_close": float(close),
            "open": result.get("o"),
            "high": result.get("h"),
            "low": result.get("l"),
            "volume": result.get("v"),
            "timestamp": result.get("t"),
            "source": "polygon_previous_close",
        }
        if getattr(response, "_email_article_analyzer_tls_verify_fallback", False):
            snapshot["tls_verify_fallback"] = "disabled_after_certificate_error"
        return snapshot


def _certifi_http_get(url, params, timeout):
    try:
        return httpx.get(url, params=params, timeout=timeout, verify=_default_ca_bundle_path())
    except httpx.ConnectError as exc:
        if "certificate" not in str(exc).lower():
            raise
        response = httpx.get(url, params=params, timeout=timeout, verify=False)
        setattr(response, "_email_article_analyzer_tls_verify_fallback", True)
        return response


def _default_ca_bundle_path() -> str:
    certifi_bundle_path = certifi.where()
    if os.name != "nt":
        return certifi_bundle_path
    output = Path(tempfile.gettempdir()) / "email_article_analyzer_ca_bundle.pem"
    output.write_bytes(Path(certifi_bundle_path).read_bytes())
    with output.open("ab") as bundle:
        for certificate, encoding, _trust in ssl.enum_certificates("ROOT"):
            if encoding != "x509_asn":
                continue
            bundle.write(ssl.DER_cert_to_PEM_cert(certificate).encode("ascii"))
    return str(output)
