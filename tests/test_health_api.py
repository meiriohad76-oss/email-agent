from fastapi.testclient import TestClient

from email_article_analyzer.main import create_app


def test_health_endpoint_reports_ok(tmp_path):
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_app_uses_orchestrator_factory_when_not_injected(tmp_path, monkeypatch):
    sentinel = object()
    calls = []

    def fake_factory(config, database_path, source_browser_session=None, run_control=None):
        calls.append((config, database_path, source_browser_session, run_control))
        return sentinel

    monkeypatch.setattr("email_article_analyzer.main.create_run_orchestrator", fake_factory)

    app = create_app(database_path=str(tmp_path / "app.db"))

    assert app.state.run_orchestrator is sentinel
    assert calls[0][1] == str(tmp_path / "app.db")
    assert calls[0][2] is app.state.source_browser_session
    assert calls[0][3] is app.state.run_control


def test_create_app_uses_article_chrome_profile_for_source_logins(tmp_path):
    app = create_app(database_path=str(tmp_path / "app.db"), run_orchestrator=object())

    assert "--remote-debugging-port=9222" in app.state.source_login_launcher.extra_args
    assert any(
        arg.startswith("--user-data-dir=") and arg.endswith("data\\user-chrome-profile")
        for arg in app.state.source_login_launcher.extra_args
    )
