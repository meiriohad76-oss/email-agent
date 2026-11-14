from email_article_analyzer.providers.polygon import PolygonHttpClient
from email_article_analyzer.providers import polygon


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


def test_polygon_previous_close_returns_market_snapshot():
    calls = []

    def fake_get(url, params, timeout):
        calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse(
            payload={
                "results": [
                    {
                        "c": 205.75,
                        "o": 203,
                        "h": 207,
                        "l": 202,
                        "v": 123456,
                        "t": 1719000000000,
                    }
                ]
            }
        )

    client = PolygonHttpClient("polygon-key", base_url="https://polygon.test", http_get=fake_get)

    snapshot = client.previous_close("AAPL")

    assert calls == [
        {
            "url": "https://polygon.test/v2/aggs/ticker/AAPL/prev",
            "params": {"apiKey": "polygon-key", "adjusted": "true"},
            "timeout": 10,
        }
    ]
    assert snapshot == {
        "ticker": "AAPL",
        "last_close": 205.75,
        "open": 203,
        "high": 207,
        "low": 202,
        "volume": 123456,
        "timestamp": 1719000000000,
        "source": "polygon_previous_close",
    }


def test_polygon_previous_close_returns_none_for_missing_ticker():
    client = PolygonHttpClient(
        "polygon-key",
        http_get=lambda url, params, timeout: FakeResponse(status_code=404),
    )

    assert client.previous_close("MISSING") is None


def test_polygon_default_http_client_uses_default_ca_bundle(monkeypatch):
    calls = []

    def fake_get(url, params, timeout, verify):
        calls.append({"url": url, "params": params, "timeout": timeout, "verify": verify})
        return FakeResponse(status_code=404)

    monkeypatch.setattr(polygon.httpx, "get", fake_get)
    monkeypatch.setattr(polygon, "_default_ca_bundle_path", lambda: "combined.pem")
    client = PolygonHttpClient("polygon-key", base_url="https://polygon.test")

    assert client.previous_close("AAPL") is None
    assert calls == [
        {
            "url": "https://polygon.test/v2/aggs/ticker/AAPL/prev",
            "params": {"apiKey": "polygon-key", "adjusted": "true"},
            "timeout": 10,
            "verify": "combined.pem",
        }
    ]


def test_polygon_default_http_client_retries_certificate_failures_without_verify(monkeypatch):
    calls = []

    def fake_get(url, params, timeout, verify):
        calls.append({"url": url, "params": params, "timeout": timeout, "verify": verify})
        if len(calls) == 1:
            raise polygon.httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
        return FakeResponse(payload={"results": [{"c": 111.22}]})

    monkeypatch.setattr(polygon.httpx, "get", fake_get)
    monkeypatch.setattr(polygon, "_default_ca_bundle_path", lambda: "combined.pem")
    client = PolygonHttpClient("polygon-key", base_url="https://polygon.test")

    snapshot = client.previous_close("AAPL")

    assert snapshot["last_close"] == 111.22
    assert snapshot["tls_verify_fallback"] == "disabled_after_certificate_error"
    assert calls == [
        {
            "url": "https://polygon.test/v2/aggs/ticker/AAPL/prev",
            "params": {"apiKey": "polygon-key", "adjusted": "true"},
            "timeout": 10,
            "verify": "combined.pem",
        },
        {
            "url": "https://polygon.test/v2/aggs/ticker/AAPL/prev",
            "params": {"apiKey": "polygon-key", "adjusted": "true"},
            "timeout": 10,
            "verify": False,
        },
    ]
