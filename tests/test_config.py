from email_article_analyzer.config import AppConfig


def test_config_loads_defaults_for_local_development(monkeypatch):
    monkeypatch.delenv("APP_DATABASE_PATH", raising=False)
    monkeypatch.delenv("APP_DASHBOARD_PASSWORD", raising=False)
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    monkeypatch.delenv("GMAIL_CREDENTIALS_PATH", raising=False)
    monkeypatch.delenv("GMAIL_TOKEN_PATH", raising=False)

    config = AppConfig.from_env()

    assert config.database_path.endswith("data/app.db")
    assert config.dashboard_password == "change-me"
    assert config.polygon_api_key is None
    assert config.gmail_credentials_path == "config/gmail_credentials.json"
    assert config.gmail_token_path == "data/gmail_token.json"


def test_config_reads_environment_overrides(monkeypatch):
    monkeypatch.setenv("APP_DATABASE_PATH", "custom/test.db")
    monkeypatch.setenv("APP_DASHBOARD_PASSWORD", "secret")
    monkeypatch.setenv("POLYGON_API_KEY", "polygon-key")
    monkeypatch.setenv("GMAIL_CREDENTIALS_PATH", "secrets/gmail.json")
    monkeypatch.setenv("GMAIL_TOKEN_PATH", "secrets/token.json")

    config = AppConfig.from_env()

    assert config.database_path == "custom/test.db"
    assert config.dashboard_password == "secret"
    assert config.polygon_api_key == "polygon-key"
    assert config.gmail_credentials_path == "secrets/gmail.json"
    assert config.gmail_token_path == "secrets/token.json"
