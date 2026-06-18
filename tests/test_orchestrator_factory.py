from email_article_analyzer.config import AppConfig
from email_article_analyzer.orchestrator_factory import create_run_orchestrator
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
        openai_api_key="openai-key",
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
