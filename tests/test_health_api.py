import base64

from fastapi.testclient import TestClient

from email_article_analyzer.application import create_app


def test_health_endpoint_reports_ok(tmp_path):
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_app_uses_orchestrator_factory_when_not_injected(tmp_path, monkeypatch):
    sentinel = object()
    calls = []

    def fake_factory(
        config,
        database_path,
        source_browser_session=None,
        browser_task_queue=None,
        run_control=None,
    ):
        calls.append(
            (config, database_path, source_browser_session, browser_task_queue, run_control)
        )
        return sentinel

    monkeypatch.setattr("email_article_analyzer.application.create_run_orchestrator", fake_factory)

    app = create_app(database_path=str(tmp_path / "app.db"))

    assert app.state.run_orchestrator is sentinel
    assert calls[0][1] == str(tmp_path / "app.db")
    assert calls[0][2] is app.state.source_browser_session
    assert calls[0][3] is app.state.browser_task_queue
    assert calls[0][4] is app.state.run_control


def test_create_app_uses_article_chrome_profile_for_source_logins(tmp_path):
    app = create_app(database_path=str(tmp_path / "app.db"), run_orchestrator=object())

    assert "--remote-debugging-port=9222" in app.state.source_login_launcher.extra_args
    assert any(
        arg.startswith("--user-data-dir=") and arg.endswith("data\\user-chrome-profile")
        for arg in app.state.source_login_launcher.extra_args
    )


def test_dashboard_password_protects_api_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DASHBOARD_PASSWORD", "secret")
    app = create_app(database_path=str(tmp_path / "app.db"), run_orchestrator=object())
    client = TestClient(app)

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/runs").status_code == 401

    token = base64.b64encode(b"user:secret").decode("ascii")
    response = client.get("/api/runs", headers={"Authorization": f"Basic {token}"})

    assert response.status_code == 200


def test_dashboard_password_accepts_bridge_header(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DASHBOARD_PASSWORD", "secret")
    app = create_app(database_path=str(tmp_path / "app.db"), run_orchestrator=object())
    client = TestClient(app)

    response = client.get(
        "/api/browser-tasks/status",
        headers={"X-Email-Article-Analyzer-Password": "secret"},
    )

    assert response.status_code == 200


def test_default_dashboard_password_allows_loopback_only(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_DASHBOARD_PASSWORD", raising=False)
    app = create_app(database_path=str(tmp_path / "app.db"), run_orchestrator=object())
    client = TestClient(app)

    local_response = client.get("/api/runs")
    remote_response = client.get("/api/runs", headers={"X-Forwarded-For": "192.168.1.45"})

    assert local_response.status_code == 200
    assert remote_response.status_code == 503
    assert "Set APP_DASHBOARD_PASSWORD" in remote_response.text
