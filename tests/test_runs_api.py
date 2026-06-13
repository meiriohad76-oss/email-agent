from fastapi.testclient import TestClient

from email_article_analyzer.db import initialize_database
from email_article_analyzer.main import create_app
from email_article_analyzer.repositories import GmailDiscoveryRepository, RunRepository
from email_article_analyzer.run_orchestration import RunResult


class FakeRunOrchestrator:
    def __init__(self):
        self.calls = []

    def start_discovery_run(self, extraction_model, summary_model):
        self.calls.append((extraction_model, summary_model))
        return RunResult(
            run_id=123,
            status="completed",
            candidate_count=2,
            needed_source_logins=["seeking_alpha", "zacks"],
        )


def test_create_run_endpoint_starts_discovery_run(tmp_path):
    fake_orchestrator = FakeRunOrchestrator()
    app = create_app(
        database_path=str(tmp_path / "app.db"),
        run_orchestrator=fake_orchestrator,
    )
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={"extraction_model": "gpt-extract", "summary_model": "gpt-summary"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "run_id": 123,
        "status": "completed",
        "candidate_count": 2,
        "needed_source_logins": ["seeking_alpha", "zacks"],
    }
    assert fake_orchestrator.calls == [("gpt-extract", "gpt-summary")]


def test_get_run_endpoint_returns_status_counts_and_events(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_repo = RunRepository(db_path)
    gmail_repo = GmailDiscoveryRepository(db_path)
    run_id = run_repo.create_run("gpt-extract", "gpt-summary")
    run_repo.add_event(run_id, "run_started", "startup", "Run started")
    message_row_id = gmail_repo.save_message(
        run_id=run_id,
        gmail_message_id="msg-1",
        thread_id="thread-1",
        sender="alerts@seekingalpha.com",
        subject="Story",
        labels=["UNREAD"],
        source_key="seeking_alpha",
        processing_status="discovered",
    )
    gmail_repo.save_article_link(
        gmail_message_row_id=message_row_id,
        source_key="seeking_alpha",
        raw_url="https://seekingalpha.com/article/1",
        normalized_url="https://seekingalpha.com/article/1",
        detection_method="headline_anchor",
        detection_confidence=0.9,
        heuristic_notes=None,
    )
    app = create_app(database_path=db_path)
    client = TestClient(app)

    response = client.get(f"/api/runs/{run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["id"] == run_id
    assert payload["run"]["status"] == "running"
    assert payload["counts"] == {"gmail_messages": 1, "article_links": 1}
    assert payload["events"][0]["event_type"] == "run_started"
