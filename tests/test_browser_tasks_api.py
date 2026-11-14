from fastapi.testclient import TestClient

from email_article_analyzer.application import create_app
from email_article_analyzer.browser_tasks import BrowserArticleTaskResult


def test_browser_task_status_reports_not_connected_until_extension_polls(tmp_path):
    app = create_app(database_path=str(tmp_path / "app.db"), run_orchestrator=object())
    client = TestClient(app)

    response = client.get("/api/browser-tasks/status")

    assert response.status_code == 200
    assert response.json() == {"status": "not_connected"}


def test_browser_task_next_marks_extension_connected(tmp_path):
    app = create_app(database_path=str(tmp_path / "app.db"), run_orchestrator=object())
    client = TestClient(app)

    next_response = client.get("/api/browser-tasks/next")
    status_response = client.get("/api/browser-tasks/status")

    assert next_response.status_code == 200
    assert next_response.json() == {"status": "idle"}
    assert status_response.json() == {"status": "connected"}


def test_browser_task_complete_rejects_unknown_or_expired_task(tmp_path):
    app = create_app(database_path=str(tmp_path / "app.db"), run_orchestrator=object())
    client = TestClient(app)

    response = client.post(
        "/api/browser-tasks/complete",
        json={
            "task_id": "task-1",
            "status": "success",
            "final_url": "https://seekingalpha.com/article/1",
            "title": "Story",
            "extracted_text": "Article text",
            "http_status": 200,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "rejected", "reason": "unknown_or_expired_task"}


def test_browser_task_test_extract_returns_bounded_preview_and_sa_snapshots(tmp_path):
    class FakeQueue:
        def submit_article_task(self, url, timeout_seconds):
            assert url == "https://seekingalpha.com/symbol/AEM/ratings/quant-ratings"
            assert timeout_seconds == 12
            return BrowserArticleTaskResult(
                task_id="task-1",
                status="success",
                final_url=url,
                title="AEM Quant Ratings",
                extracted_text=(
                    "SA_DATA SCRIPT_DATA.props.pageProps.currentQuantRating.rating = Buy\n"
                    "SA_DATA SCRIPT_DATA.props.pageProps.currentQuantRating.score = 3.88\n"
                    + ("x" * 5000)
                ),
                http_status=200,
            )

    app = create_app(database_path=str(tmp_path / "app.db"), run_orchestrator=object())
    app.state.browser_task_queue = FakeQueue()
    client = TestClient(app)

    response = client.post(
        "/api/browser-tasks/test-extract",
        json={
            "url": "https://seekingalpha.com/symbol/AEM/ratings/quant-ratings",
            "timeout_seconds": 12,
            "ticker": "AEM",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["text_char_count"] == 5136
    assert len(payload["text_preview"]) <= 2000
    assert "extracted_text" not in payload
    assert payload["parsed_seeking_alpha_snapshots"][0]["rating"] == "Buy"


def test_browser_task_test_extract_can_return_full_text_for_local_diagnostics(tmp_path):
    class FakeQueue:
        def submit_article_task(self, url, timeout_seconds):
            return BrowserArticleTaskResult(
                task_id="task-1",
                status="success",
                final_url=url,
                title="AAPL Metrics",
                extracted_text="full authenticated page text",
                http_status=200,
            )

    app = create_app(database_path=str(tmp_path / "app.db"), run_orchestrator=object())
    app.state.browser_task_queue = FakeQueue()
    client = TestClient(app)

    response = client.post(
        "/api/browser-tasks/test-extract",
        json={
            "url": "https://seekingalpha.com/symbol/AAPL/valuation/metrics",
            "ticker": "AAPL",
            "include_full_text": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["extracted_text"] == "full authenticated page text"


def test_browser_task_test_extract_returns_zacks_snapshots(tmp_path):
    class FakeQueue:
        def submit_article_task(self, url, timeout_seconds):
            return BrowserArticleTaskResult(
                task_id="task-1",
                status="success",
                final_url=url,
                title="AAPL Quote",
                extracted_text="Zacks Rank #2 (Buy)",
                http_status=200,
            )

    app = create_app(database_path=str(tmp_path / "app.db"), run_orchestrator=object())
    app.state.browser_task_queue = FakeQueue()
    client = TestClient(app)

    response = client.post(
        "/api/browser-tasks/test-extract",
        json={
            "url": "https://www.zacks.com/stock/quote/AAPL",
            "ticker": "AAPL",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["parsed_zacks_snapshots"][0]["rating"] == "Rank #2 Buy"
