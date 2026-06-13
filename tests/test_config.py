from email_article_analyzer.config import AppConfig


def test_config_loads_defaults_for_local_development(monkeypatch):
    monkeypatch.delenv("APP_DATABASE_PATH", raising=False)
    monkeypatch.delenv("APP_DASHBOARD_PASSWORD", raising=False)
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)

    config = AppConfig.from_env()

    assert config.database_path.endswith("data/app.db")
    assert config.dashboard_password == "change-me"
    assert config.polygon_api_key is None


def test_config_reads_environment_overrides(monkeypatch):
    monkeypatch.setenv("APP_DATABASE_PATH", "custom/test.db")
    monkeypatch.setenv("APP_DASHBOARD_PASSWORD", "secret")
    monkeypatch.setenv("POLYGON_API_KEY", "polygon-key")

    config = AppConfig.from_env()

    assert config.database_path == "custom/test.db"
    assert config.dashboard_password == "secret"
    assert config.polygon_api_key == "polygon-key"
