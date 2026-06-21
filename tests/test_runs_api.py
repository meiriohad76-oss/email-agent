from fastapi.testclient import TestClient

from email_article_analyzer.db import initialize_database
from email_article_analyzer.main import create_app
from email_article_analyzer.model_defaults import DEFAULT_EXTRACTION_MODEL
from email_article_analyzer.model_defaults import DEFAULT_SUMMARY_MODEL
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


class FailingRunOrchestrator:
    def start_discovery_run(self, extraction_model, summary_model):
        raise RuntimeError("Gmail API TLS verification failed")


def configure_ready_essentials(tmp_path, monkeypatch):
    credentials_path = tmp_path / "gmail_credentials.json"
    token_path = tmp_path / "gmail_token.json"
    credentials_path.write_text("{}", encoding="utf-8")
    token_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("GMAIL_CREDENTIALS_PATH", str(credentials_path))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(token_path))


def test_create_run_endpoint_starts_discovery_run(tmp_path, monkeypatch):
    configure_ready_essentials(tmp_path, monkeypatch)
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


def test_create_run_endpoint_normalizes_blank_models_to_defaults(tmp_path, monkeypatch):
    configure_ready_essentials(tmp_path, monkeypatch)
    fake_orchestrator = FakeRunOrchestrator()
    app = create_app(
        database_path=str(tmp_path / "app.db"),
        run_orchestrator=fake_orchestrator,
    )
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={"extraction_model": "  ", "summary_model": None},
    )

    assert response.status_code == 200
    assert fake_orchestrator.calls == [
        (DEFAULT_EXTRACTION_MODEL, DEFAULT_SUMMARY_MODEL)
    ]


def test_create_run_endpoint_rejects_object_model_values(tmp_path, monkeypatch):
    configure_ready_essentials(tmp_path, monkeypatch)
    fake_orchestrator = FakeRunOrchestrator()
    app = create_app(
        database_path=str(tmp_path / "app.db"),
        run_orchestrator=fake_orchestrator,
    )
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={"extraction_model": {"name": "gpt"}, "summary_model": "gpt-summary"},
    )

    assert response.status_code == 422
    assert "model name must be a string" in response.text
    assert fake_orchestrator.calls == []


def test_create_run_endpoint_rejects_when_essential_providers_are_not_ready(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GMAIL_CREDENTIALS_PATH", str(tmp_path / "missing_credentials.json"))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "missing_token.json"))
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

    assert response.status_code == 409
    assert response.json()["detail"]["missing_essential_providers"] == ["openai", "gmail"]
    assert fake_orchestrator.calls == []


def test_create_run_endpoint_returns_bad_gateway_when_orchestrator_fails(tmp_path, monkeypatch):
    configure_ready_essentials(tmp_path, monkeypatch)
    app = create_app(
        database_path=str(tmp_path / "app.db"),
        run_orchestrator=FailingRunOrchestrator(),
    )
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={"extraction_model": "gpt-extract", "summary_model": "gpt-summary"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "message": "Discovery run failed",
        "error": "Gmail API TLS verification failed",
    }


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
    link_id = gmail_repo.save_article_link(
        gmail_message_row_id=message_row_id,
        source_key="seeking_alpha",
        raw_url="https://seekingalpha.com/article/1",
        normalized_url="https://seekingalpha.com/article/1",
        detection_method="headline_anchor",
        detection_confidence=0.9,
        heuristic_notes=None,
    )
    gmail_repo.save_article_content(
        article_link_id=link_id,
        fetch_status="fetched",
        final_url="https://seekingalpha.com/article/1",
        http_status=200,
        title="Story title",
        extracted_text="Article body text.",
        failure_reason=None,
    )
    gmail_repo.save_article_analysis(
        article_link_id=link_id,
        provider="openai",
        model="gpt-summary",
        summary="Margins improved.",
        stance="buy_watch",
        confidence=0.82,
        supporting_evidence=["Raised guide", "Margin expansion"],
        mentioned_tickers=["NVDA"],
        raw_response={"id": "resp-1"},
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
    assert payload["articles"] == [
        {
            "article_link_id": 1,
            "gmail_message_id": "msg-1",
            "sender": "alerts@seekingalpha.com",
            "subject": "Story",
            "message_status": "discovered",
            "source_key": "seeking_alpha",
            "normalized_url": "https://seekingalpha.com/article/1",
            "detection_method": "headline_anchor",
            "detection_confidence": 0.9,
            "content": {
                "fetch_status": "fetched",
                "title": "Story title",
                "text_char_count": len("Article body text."),
                "failure_reason": None,
            },
            "analysis": {
                "provider": "openai",
                "model": "gpt-summary",
                "summary": "Margins improved.",
                "stance": "buy_watch",
                "sentiment": "unclear",
                "recommendation": "unclear",
                "confidence": 0.82,
                "supporting_evidence": ["Raised guide", "Margin expansion"],
                "mentioned_tickers": ["NVDA"],
                "mentioned_ticker_details": [
                    {"ticker": "NVDA", "in_portfolio": False},
                ],
                "price_targets": [],
                "actionable_data": [],
            },
        }
    ]


def test_list_runs_endpoint_returns_recent_runs_with_counts(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_repo = RunRepository(db_path)
    gmail_repo = GmailDiscoveryRepository(db_path)
    older_run_id = run_repo.create_run("older-extract", "older-summary")
    newer_run_id = run_repo.create_run("newer-extract", "newer-summary")
    run_repo.complete_run(newer_run_id)
    message_row_id = gmail_repo.save_message(
        run_id=newer_run_id,
        gmail_message_id="msg-2",
        thread_id="thread-2",
        sender="alerts@zacks.com",
        subject="Newer Story",
        labels=["UNREAD"],
        source_key="zacks",
        processing_status="discovered",
    )
    gmail_repo.save_article_link(
        gmail_message_row_id=message_row_id,
        source_key="zacks",
        raw_url="https://www.zacks.com/article/2",
        normalized_url="https://www.zacks.com/article/2",
        detection_method="headline_anchor",
        detection_confidence=0.91,
        heuristic_notes=None,
    )
    app = create_app(database_path=db_path)
    client = TestClient(app)

    response = client.get("/api/runs")

    assert response.status_code == 200
    payload = response.json()
    assert [run["id"] for run in payload["runs"]] == [newer_run_id, older_run_id]
    assert payload["runs"][0]["status"] == "completed"
    assert payload["runs"][0]["counts"] == {"gmail_messages": 1, "article_links": 1}
    assert payload["runs"][1]["counts"] == {"gmail_messages": 0, "article_links": 0}
