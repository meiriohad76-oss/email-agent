from email_article_analyzer.db import initialize_database
from email_article_analyzer.repositories import RunRepository


def test_run_repository_creates_run_and_event(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    repo = RunRepository(db_path)

    run_id = repo.create_run(
        extraction_model="gpt-test-extract",
        summary_model="gpt-test-summary",
    )
    repo.add_event(
        run_id=run_id,
        event_type="run_started",
        stage="startup",
        message="Run started",
        details={"source": "test"},
    )

    run = repo.get_run(run_id)
    events = repo.list_events(run_id)

    assert run["status"] == "running"
    assert run["extraction_model"] == "gpt-test-extract"
    assert events[0]["event_type"] == "run_started"
    assert events[0]["details_json"] == '{"source": "test"}'


def test_run_repository_completes_run_and_counts_discovery_rows(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_repo = RunRepository(db_path)
    from email_article_analyzer.repositories import GmailDiscoveryRepository

    gmail_repo = GmailDiscoveryRepository(db_path)
    run_id = run_repo.create_run(extraction_model=None, summary_model=None)
    message_id = gmail_repo.save_message(
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
        gmail_message_row_id=message_id,
        source_key="seeking_alpha",
        raw_url="https://seekingalpha.com/article/1",
        normalized_url="https://seekingalpha.com/article/1",
        detection_method="headline_anchor",
        detection_confidence=0.9,
        heuristic_notes=None,
    )

    run_repo.complete_run(run_id)
    counts = run_repo.discovery_counts(run_id)
    run = run_repo.get_run(run_id)

    assert run["status"] == "completed"
    assert run["completed_at"] is not None
    assert counts == {"gmail_messages": 1, "article_links": 1}
