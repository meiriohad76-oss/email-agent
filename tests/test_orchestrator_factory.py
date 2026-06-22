from email_article_analyzer.config import AppConfig
from email_article_analyzer.orchestrator_factory import (
    _build_ca_bundle,
    _build_gmail_service,
    _create_article_content_fetcher,
    _create_openai_client,
    create_run_orchestrator,
)
from email_article_analyzer.providers.gmail_api import GmailApiProvider
from email_article_analyzer.run_orchestration import RunOrchestrator


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
    assert orchestrator.article_analyzer.client["api_key"] == "openai-key"


def test_build_gmail_service_uses_certifi_ca_bundle():
    calls = {}

    class FakeHttp:
        def __init__(self, ca_certs):
            calls["ca_certs"] = ca_certs

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
    )

    assert service == {"service": "gmail"}
    assert calls["ca_certs"] == "certifi.pem"
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
    assert fetcher.browser_domains == ("seekingalpha.com", "zacks.com")
    assert calls["verify"] == "combined.pem"


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
