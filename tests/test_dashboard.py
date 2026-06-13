from fastapi.testclient import TestClient

from email_article_analyzer.main import create_app


def test_dashboard_route_serves_operational_shell(tmp_path):
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Email Article Analyzer" in response.text
    assert "watchlist-upload" in response.text
    assert "run-start-form" in response.text
    assert "run-lookup-form" in response.text


def test_dashboard_assets_are_served(tmp_path):
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    css_response = client.get("/static/dashboard.css")
    js_response = client.get("/static/dashboard.js")

    assert css_response.status_code == 200
    assert "dashboard-shell" in css_response.text
    assert js_response.status_code == 200
    assert "watchlist-upload" in js_response.text
