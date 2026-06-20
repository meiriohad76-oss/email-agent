from fastapi.testclient import TestClient

from email_article_analyzer.main import create_app


def test_confirm_source_logins_endpoint_persists_acknowledgement(tmp_path, monkeypatch):
    confirmation_path = tmp_path / "source-logins.json"
    monkeypatch.setenv("SOURCE_LOGIN_CONFIRMATION_PATH", str(confirmation_path))
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    response = client.post(
        "/api/source-logins/confirm",
        json={"sources": ["seeking_alpha"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["sources"] == ["seeking_alpha"]
    assert "seeking_alpha" in confirmation_path.read_text(encoding="utf-8")
