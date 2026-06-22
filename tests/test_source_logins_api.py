from fastapi.testclient import TestClient

from email_article_analyzer.main import create_app


def test_confirm_source_logins_endpoint_persists_acknowledgement(tmp_path, monkeypatch):
    confirmation_path = tmp_path / "source-logins.json"
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


def test_open_source_login_endpoint_opens_all_sources_in_regular_chrome(tmp_path):
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
        "status": "opened",
        "source": "all",
        "opened_sources": [
            {"source": "seeking_alpha", "url": "https://seekingalpha.com/"},
            {"source": "zacks", "url": "https://www.zacks.com/login"},
        ],
    }
    assert chrome_launcher.urls == [
        "https://seekingalpha.com/",
        "https://www.zacks.com/login",
    ]
