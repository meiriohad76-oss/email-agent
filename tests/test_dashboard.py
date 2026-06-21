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
    assert "start-run-button" in response.text
    assert "run-readiness-message" in response.text
    assert "provider-status-list" in response.text
    assert "source-login-open-button" in response.text
    assert "source-login-confirm-button" in response.text
    assert 'value="gpt-5.4"' in response.text
    assert 'value="gpt-5.4-mini"' in response.text
    assert "run-lookup-form" in response.text
    assert "run-detail-summary" in response.text
    assert "run-event-timeline" in response.text
    assert "run-article-list" in response.text


def test_dashboard_assets_are_served(tmp_path):
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    css_response = client.get("/static/dashboard.css")
    js_response = client.get("/static/dashboard.js")

    assert css_response.status_code == 200
    assert "dashboard-shell" in css_response.text
    assert js_response.status_code == 200
    assert "watchlist-upload" in js_response.text
    assert "recent-runs-list" in js_response.text
    assert "refreshProviderStatus" in js_response.text
    assert "updateRunStartAvailability" in js_response.text
    assert "essential provider" in js_response.text
    assert "setup_steps" in js_response.text
    assert "provider-status-item" in css_response.text
    assert "provider-setup-step" in css_response.text
    assert "button:disabled" in css_response.text
    assert "renderRunDetail" in js_response.text
    assert "formatApiError" in js_response.text
    assert "formatContentStatus" in js_response.text
    assert "openSourceLoginBrowser" in js_response.text
    assert "confirmSourceLogins" in js_response.text
    assert 'String(form.get("extraction_model") || "").trim()' in js_response.text
    assert 'String(form.get("summary_model") || "").trim()' in js_response.text
    assert "window.setInterval(refreshRecentRuns, 5000)" in js_response.text
    assert "window.clearInterval(progressRefresh)" in js_response.text
    assert "email fallback" in js_response.text
    assert "payload.detail" in js_response.text
    assert "renderArticleRows" in js_response.text
    assert "source-login-warning-list" in js_response.text
    assert "article-analysis" in js_response.text
    assert "supporting_evidence" in js_response.text
    assert "fetch_status" in js_response.text
    assert "article-row" in css_response.text
    assert "article-fetch-status.email_fallback" in css_response.text
    assert ".article-analysis" in css_response.text
    assert "event-timeline-row" in css_response.text
