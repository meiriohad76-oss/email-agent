from fastapi.testclient import TestClient

from email_article_analyzer.application import create_app


def test_dashboard_route_serves_operational_shell(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DASHBOARD_PASSWORD", "change-me")
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Email Article Analyzer" in response.text
    assert "watchlist-upload" in response.text
    assert "run-start-form" in response.text
    assert "start-run-button" in response.text
    assert "stop-run-button" in response.text
    assert "export-report-button" in response.text
    assert "retry-enrichments-button" in response.text
    assert "retry-gmail-marks-button" in response.text
    assert "run-readiness-message" in response.text
    assert "provider-status-list" in response.text
    assert "source-login-open-sa-button" in response.text
    assert "source-login-open-zacks-button" in response.text
    assert "source-login-open-investing-button" in response.text
    assert "source-login-confirm-button" in response.text
    assert "Open Seeking Alpha" in response.text
    assert "Open Zacks" in response.text
    assert "Open Investing" in response.text
    assert "browser-bridge-status" in response.text
    assert "/static/dashboard.js?v=20260808-source-login-popup-fallback" in response.text
    assert "Precheck model" in response.text
    assert 'value="gpt-5.6-luna"' in response.text
    assert 'value="gpt-5.6-terra"' in response.text
    assert "run-lookup-form" in response.text
    assert "run-detail-summary" in response.text
    assert "run-event-timeline" in response.text
    assert "run-article-list" in response.text
    assert "run-enrichment-list" in response.text
    assert 'href="/research"' in response.text


def test_dashboard_assets_are_served(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DASHBOARD_PASSWORD", "change-me")
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
    assert "openSourceLogin" in js_response.text
    assert "confirmSourceLogins" in js_response.text
    assert "refreshBrowserBridgeStatus" in js_response.text
    assert "/api/browser-tasks/status" in js_response.text
    assert "Chrome bridge not connected" in js_response.text
    assert "Start disabled until the Chrome bridge extension is connected." in js_response.text
    assert "https://seekingalpha.com/" in js_response.text
    assert "https://www.zacks.com/login" in js_response.text
    assert "https://www.investing.com/" in js_response.text
    assert 'window.open("about:blank", "_blank")' in js_response.text
    assert "tab.location.href = url" in js_response.text
    assert "Chrome blocked the popup" in js_response.text
    assert 'JSON.stringify({ sources: ["seeking_alpha", "zacks", "investing"] })' in js_response.text
    assert 'String(form.get("extraction_model") || "").trim()' in js_response.text
    assert 'String(form.get("summary_model") || "").trim()' in js_response.text
    assert "extraction_model: extractionModel || null" in js_response.text
    assert "Precheck model" in js_response.text
    assert "Article analysis model" in js_response.text
    assert "Report synthesis model" in js_response.text
    assert "window.setInterval(refreshRecentRuns, 5000)" in js_response.text
    assert "window.clearInterval(progressRefresh)" in js_response.text
    assert "stopCurrentRun" in js_response.text
    assert "/api/runs/stop-current" in js_response.text
    assert "exportRunReport" in js_response.text
    assert "/report.pdf" in js_response.text
    assert "retryRunEnrichments" in js_response.text
    assert "/retry-enrichments" in js_response.text
    assert "retryGmailMarks" in js_response.text
    assert "/retry-gmail-marks" in js_response.text
    assert "deleteRun" in js_response.text
    assert 'method: "DELETE"' in js_response.text
    assert "data-run-delete-id" in js_response.text
    assert "data-run-pdf-id" in js_response.text
    assert "Started" in js_response.text
    assert "Completed" in js_response.text
    assert "run-row-actions" in css_response.text
    assert "compact-button" in css_response.text
    assert "async function loadRunDetail" in js_response.text
    assert "await loadRunDetail(" in js_response.text
    assert "Run completed. Loaded details" in js_response.text
    assert "payload.alerts" in js_response.text
    assert "email fallback" in js_response.text
    assert "payload.detail" in js_response.text
    assert "renderArticleRows" in js_response.text
    assert "renderTickerEnrichments" in js_response.text
    assert "ticker_enrichments" in js_response.text
    assert "Ticker enrichments" in js_response.text
    assert "formatTickerEnrichment" in js_response.text
    assert "formatInvestingProEnrichment" in js_response.text
    assert "polygonLastCloseByTicker" in js_response.text
    assert "formatTargetWithPolygonBaseline" in js_response.text
    assert "Polygon upside" in js_response.text
    assert "Source upside" in js_response.text
    assert "enrichment-row ${enrichment.status" in js_response.text
    assert "source-login-warning-list" in js_response.text
    assert "article-analysis" in js_response.text
    assert "supporting_evidence" in js_response.text
    assert "fetch_status" in js_response.text
    assert "mentioned_ticker_details" in js_response.text
    assert "price_targets" in js_response.text
    assert "actionable_data" in js_response.text
    assert "Recommendation" in js_response.text
    assert "in-portfolio" in css_response.text
    assert "not-in-portfolio" in css_response.text
    assert "article-row" in css_response.text
    assert "article-fetch-status.email_fallback" in css_response.text
    assert ".article-analysis" in css_response.text
    assert "event-timeline-row" in css_response.text
    assert "enrichment-row" in css_response.text


def test_research_dashboard_assets_are_served(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DASHBOARD_PASSWORD", "change-me")
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    response = client.get("/research")
    css_response = client.get("/static/research.css")
    js_response = client.get("/static/research.js")

    assert response.status_code == 200
    assert "Investment Research" in response.text
    assert "company-table-body" in response.text
    assert "compare-view" in response.text
    assert "quality-view" in response.text
    assert "Walk me through" in response.text
    assert "guide-content" in response.text
    assert "retry-source-issues" in response.text
    assert "retry-access-blocked" in response.text
    assert "data-tooltip" in response.text
    assert "Not extracted" in response.text
    assert "bulk-extract-start" in response.text
    assert "Complete all unextracted" in response.text
    assert "Source issues" in response.text
    assert "Macro rank" in response.text
    assert "Sector rank" in response.text
    assert "Macro regime" in response.text
    assert css_response.status_code == 200
    assert "workspace-grid" in css_response.text
    assert "[data-tooltip]::after" in css_response.text
    assert "detail-actions" in css_response.text
    assert "bulk-extraction-bar" in css_response.text
    assert "guide-step" in css_response.text
    assert js_response.status_code == 200
    assert "/api/research/universe" in js_response.text
    assert "renderCompanyDetail" in js_response.text
    assert "reextractCompany" in js_response.text
    assert 'force: "true", allow_unlisted: "true"' in js_response.text
    assert "Re-extract company" in js_response.text
    assert "startBulkExtraction" in js_response.text
    assert "refreshBulkStatus" in js_response.text
    assert "/api/research/bulk-extraction/start" in js_response.text
    assert "/api/research/source-issues/retry" in js_response.text
    assert "include_access_blocked" in js_response.text
    assert 'addEventListener("click", () => retrySourceIssues(false))' in js_response.text
    assert "includeAccessBlocked = includeAccessBlocked === true" in js_response.text
    assert "renderGuide" in js_response.text
    assert "PROVIDER DOES NOT SUPPLY" in js_response.text
    assert "PARSER GAPS" in js_response.text
