from fastapi.testclient import TestClient

from email_article_analyzer.application import create_app


def test_confirm_source_logins_endpoint_persists_acknowledgement(tmp_path, monkeypatch):
    confirmation_path = tmp_path / "source-logins.json"
    monkeypatch.setenv("APP_DASHBOARD_PASSWORD", "change-me")
    monkeypatch.setenv("SOURCE_LOGIN_CONFIRMATION_PATH", str(confirmation_path))
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    response = client.post(
        "/api/source-logins/confirm",
        json={"sources": ["seeking_alpha", "zacks"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["sources"] == ["seeking_alpha", "zacks"]
    assert "seeking_alpha" in confirmation_path.read_text(encoding="utf-8")
    assert "zacks" in confirmation_path.read_text(encoding="utf-8")


def test_open_source_login_endpoint_no_longer_launches_chrome_from_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DASHBOARD_PASSWORD", "change-me")

    class FakeChromeLauncher:
        def __init__(self):
            self.urls = []

        def open_url(self, url):
            self.urls.append(url)

    chrome_launcher = FakeChromeLauncher()
    app = create_app(database_path=str(tmp_path / "app.db"))
    app.state.source_login_launcher = chrome_launcher
    client = TestClient(app)

    response = client.post(
        "/api/source-logins/open",
        json={"source": "all"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "browser_open_required",
        "source": "all",
        "opened_sources": [],
        "login_urls": [
            {"source": "seeking_alpha", "url": "https://seekingalpha.com/"},
            {"source": "zacks", "url": "https://www.zacks.com/login"},
            {"source": "investing", "url": "https://www.investing.com/"},
        ],
        "message": "Open these URLs from dashboard JavaScript so Chrome creates tabs in the current window.",
    }
    assert chrome_launcher.urls == []


def test_source_login_urls_endpoint_returns_urls_for_dashboard_tabs(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DASHBOARD_PASSWORD", "change-me")
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    response = client.get("/api/source-logins/urls?source=all")

    assert response.status_code == 200
    assert response.json() == {
        "source": "all",
        "login_urls": [
            {"source": "seeking_alpha", "url": "https://seekingalpha.com/"},
            {"source": "zacks", "url": "https://www.zacks.com/login"},
            {"source": "investing", "url": "https://www.investing.com/"},
        ],
    }
