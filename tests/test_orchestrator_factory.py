from email_article_analyzer.config import AppConfig
from email_article_analyzer.orchestrator_factory import (
    _build_ca_bundle,
    _build_gmail_service,
    _create_article_content_fetcher,
    _create_openai_client,
    _resolve_project_path,
    create_run_orchestrator,
)
from pathlib import Path

from email_article_analyzer.providers.gmail_api import GmailApiProvider
from email_article_analyzer.run_orchestration import RunOrchestrator
from email_article_analyzer.article_content import UserChromeArticleContentFetcher
from email_article_analyzer.article_content import BrowserExtensionArticleContentFetcher
from email_article_analyzer.rating_enrichment import TickerRatingEnrichmentService


class FakeCredentials:
    calls = []

    @classmethod
    def from_authorized_user_file(cls, token_path, scopes):
        cls.calls.append((token_path, scopes))
        return cls()


class FakeGmailService:
    pass


def fake_build(api_name, api_version, credentials):
    return {
        "api_name": api_name,
        "api_version": api_version,
        "credentials": credentials,
        "service": FakeGmailService(),
    }


class FakeOpenAIClient:
    pass


def fake_openai_client_factory(api_key):
    return {"api_key": api_key, "client": FakeOpenAIClient()}


def test_create_run_orchestrator_returns_none_when_gmail_token_is_missing(tmp_path):
    config = AppConfig(
        database_path=str(tmp_path / "app.db"),
        dashboard_password="secret",
        polygon_api_key=None,
        openai_api_key="openai-key",
        gmail_credentials_path=str(tmp_path / "gmail_credentials.json"),
        gmail_token_path=str(tmp_path / "missing_token.json"),
    )

    orchestrator = create_run_orchestrator(config, config.database_path)

    assert orchestrator is None


def test_create_run_orchestrator_wires_real_gmail_provider(tmp_path):
    token_path = tmp_path / "gmail_token.json"
    token_path.write_text("{}", encoding="utf-8")
    config = AppConfig(
        database_path=str(tmp_path / "app.db"),
        dashboard_password="secret",
        polygon_api_key=None,
        openai_api_key=None,
        gmail_credentials_path=str(tmp_path / "gmail_credentials.json"),
        gmail_token_path=str(token_path),
    )
    FakeCredentials.calls = []

    orchestrator = create_run_orchestrator(
        config,
        config.database_path,
        credentials_cls=FakeCredentials,
        service_builder=fake_build,
    )

    assert isinstance(orchestrator, RunOrchestrator)
    provider = orchestrator.discovery_service.provider
    assert isinstance(provider, GmailApiProvider)
    assert provider.service["api_name"] == "gmail"
    assert provider.service["api_version"] == "v1"
    assert FakeCredentials.calls[0][0] == str(token_path)
    assert "https://www.googleapis.com/auth/gmail.modify" in FakeCredentials.calls[0][1]


def test_create_run_orchestrator_wires_openai_analyzer_when_api_key_exists(tmp_path):
    token_path = tmp_path / "gmail_token.json"
    token_path.write_text("{}", encoding="utf-8")
    config = AppConfig(
        database_path=str(tmp_path / "app.db"),
        dashboard_password="secret",
        polygon_api_key=None,
        openai_api_key="openai-key",
        gmail_credentials_path=str(tmp_path / "gmail_credentials.json"),
        gmail_token_path=str(token_path),
    )

    orchestrator = create_run_orchestrator(
        config,
        config.database_path,
        credentials_cls=FakeCredentials,
        service_builder=fake_build,
        openai_client_factory=fake_openai_client_factory,
    )

    assert orchestrator.article_analyzer is not None
    assert orchestrator.article_content_fetcher is not None
    assert isinstance(orchestrator.rating_enricher, TickerRatingEnrichmentService)
    assert orchestrator.rating_enricher.fetcher is orchestrator.article_content_fetcher
    assert orchestrator.article_analyzer.client["api_key"] == "openai-key"
    assert orchestrator.gmail_mark_timeout_seconds == config.gmail_api_timeout_seconds + 5.0


def test_create_run_orchestrator_wires_polygon_client_when_api_key_exists(tmp_path):
    token_path = tmp_path / "gmail_token.json"
    token_path.write_text("{}", encoding="utf-8")
    config = AppConfig(
        database_path=str(tmp_path / "app.db"),
        dashboard_password="secret",
        polygon_api_key="polygon-key",
        openai_api_key="openai-key",
        gmail_credentials_path=str(tmp_path / "gmail_credentials.json"),
        gmail_token_path=str(token_path),
    )

    orchestrator = create_run_orchestrator(
        config,
        config.database_path,
        credentials_cls=FakeCredentials,
        service_builder=fake_build,
        openai_client_factory=fake_openai_client_factory,
    )

    assert orchestrator.rating_enricher.polygon_client is not None
    assert orchestrator.rating_enricher.polygon_client.api_key == "polygon-key"


def test_resolve_project_path_does_not_depend_on_process_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    resolved = _resolve_project_path("data/investing_instrument_mapping.csv")

    assert Path(resolved) == (
        Path(__file__).resolve().parents[1] / "data" / "investing_instrument_mapping.csv"
    )


def test_build_gmail_service_uses_certifi_ca_bundle():
    calls = {}

    class FakeHttp:
        def __init__(self, ca_certs, timeout):
            calls["ca_certs"] = ca_certs
            calls["timeout"] = timeout

    class FakeAuthorizedHttp:
        def __init__(self, credentials, http):
            calls["credentials"] = credentials
            calls["http"] = http

    def fake_build(api_name, api_version, http):
        calls["api_name"] = api_name
        calls["api_version"] = api_version
        calls["authorized_http"] = http
        return {"service": "gmail"}

    service = _build_gmail_service(
        credentials="creds",
        api_builder=fake_build,
        http_cls=FakeHttp,
        authorized_http_cls=FakeAuthorizedHttp,
        ca_bundle_path="certifi.pem",
        timeout_seconds=12.5,
    )

    assert service == {"service": "gmail"}
    assert calls["ca_certs"] == "certifi.pem"
    assert calls["timeout"] == 12.5
    assert calls["credentials"] == "creds"
    assert isinstance(calls["http"], FakeHttp)
    assert calls["api_name"] == "gmail"
    assert calls["api_version"] == "v1"
    assert isinstance(calls["authorized_http"], FakeAuthorizedHttp)


def test_build_ca_bundle_appends_windows_root_certificates(tmp_path):
    certifi_bundle = tmp_path / "certifi.pem"
    certifi_bundle.write_text("CERTIFI\n", encoding="utf-8")
    output_bundle = tmp_path / "combined.pem"

    bundle_path = _build_ca_bundle(
        certifi_bundle_path=str(certifi_bundle),
        output_path=output_bundle,
        windows_certificates=[(b"certificate-bytes", "x509_asn", True)],
        der_to_pem=lambda certificate: f"PEM:{certificate.decode('ascii')}\n",
    )

    assert bundle_path == str(output_bundle)
    bundle_text = output_bundle.read_text(encoding="utf-8")
    assert "CERTIFI" in bundle_text
    assert "PEM:certificate-bytes" in bundle_text


def test_create_openai_client_uses_verified_http_client():
    calls = {}

    class FakeHttpClient:
        def __init__(self, verify):
            calls["verify"] = verify

    class FakeOpenAI:
        def __init__(self, api_key, http_client):
            calls["api_key"] = api_key
            calls["http_client"] = http_client

    client = _create_openai_client(
        "openai-key",
        openai_cls=FakeOpenAI,
        http_client_cls=FakeHttpClient,
        ca_bundle_path="combined.pem",
        tls_verify=True,
    )

    assert isinstance(client, FakeOpenAI)
    assert calls["api_key"] == "openai-key"
    assert isinstance(calls["http_client"], FakeHttpClient)
    assert calls["verify"] == "combined.pem"


def test_create_openai_client_can_disable_tls_verification():
    calls = {}

    class FakeHttpClient:
        def __init__(self, verify):
            calls["verify"] = verify

    class FakeOpenAI:
        def __init__(self, api_key, http_client):
            calls["http_client"] = http_client

    _create_openai_client(
        "openai-key",
        openai_cls=FakeOpenAI,
        http_client_cls=FakeHttpClient,
        ca_bundle_path="combined.pem",
        tls_verify=False,
    )

    assert calls["verify"] is False


def test_create_article_content_fetcher_uses_verified_http_client():
    calls = {}

    class FakeHttpClient:
        def __init__(self, verify):
            calls["verify"] = verify

    fetcher = _create_article_content_fetcher(
        http_client_cls=FakeHttpClient,
        ca_bundle_path="combined.pem",
        tls_verify=True,
    )

    assert isinstance(fetcher.http_fetcher.http_client, FakeHttpClient)
    assert fetcher.browser_domains == ("seekingalpha.com", "zacks.com", "investing.com")
    assert calls["verify"] == "combined.pem"


def test_create_article_content_fetcher_uses_regular_chrome_cdp_for_source_domains():
    fetcher = _create_article_content_fetcher(article_page_pause_seconds=7.0)

    assert isinstance(fetcher.browser_fetcher, UserChromeArticleContentFetcher)
    assert fetcher.browser_fetcher.page_pause_seconds == 7.0


def test_create_article_content_fetcher_uses_browser_bridge_when_queue_is_available():
    queue = object()

    fetcher = _create_article_content_fetcher(
        browser_task_queue=queue,
        article_page_pause_seconds=7.0,
    )

    assert isinstance(fetcher.browser_fetcher, BrowserExtensionArticleContentFetcher)
    assert fetcher.browser_fetcher.browser_task_queue is queue
    assert fetcher.browser_fetcher.page_pause_seconds == 7.0


def test_create_article_content_fetcher_can_disable_tls_verification():
    calls = {}

    class FakeHttpClient:
        def __init__(self, verify):
            calls["verify"] = verify

    _create_article_content_fetcher(
        http_client_cls=FakeHttpClient,
        ca_bundle_path="combined.pem",
        tls_verify=False,
    )

    assert calls["verify"] is False
