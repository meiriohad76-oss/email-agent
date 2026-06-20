from fastapi.testclient import TestClient

from email_article_analyzer.main import create_app


def test_provider_status_reports_ready_and_missing_prerequisites(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    credentials_path = tmp_path / "gmail_credentials.json"
    credentials_path.write_text("{}", encoding="utf-8")
    missing_token_path = tmp_path / "gmail_token.json"
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    monkeypatch.setenv("GMAIL_CREDENTIALS_PATH", str(credentials_path))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(missing_token_path))
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    response = client.get("/api/status/providers")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_status"] == "action_required"
    assert payload["providers"]["openai"]["status"] == "ready"
    assert payload["providers"]["polygon"]["status"] == "missing"
    assert payload["providers"]["polygon"]["setup_steps"] == [
        "Set POLYGON_API_KEY in the environment or .env file"
    ]
    assert payload["providers"]["gmail"]["status"] == "action_required"
    assert "Gmail token file is missing" in payload["providers"]["gmail"]["details"]
    assert (
        f"Complete Gmail OAuth and save token at {missing_token_path}"
        in payload["providers"]["gmail"]["setup_steps"]
    )
    assert payload["providers"]["source_logins"]["status"] == "action_required"
    assert "Confirm source website sessions before extraction" in payload["providers"]["source_logins"]["setup_steps"]
