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
