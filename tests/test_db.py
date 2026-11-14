import sqlite3

from email_article_analyzer.db import initialize_database
from email_article_analyzer.repositories import ActiveRunError, RunRepository


def table_names(db_path):
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {row[0] for row in rows}


def test_initialize_database_creates_foundation_tables(tmp_path):
    db_path = tmp_path / "app.db"

    initialize_database(str(db_path))

    assert {
        "runs",
        "run_events",
        "watchlist_uploads",
        "watchlist_items",
        "portfolio_lots",
        "trusted_sources",
        "gmail_messages",
        "article_links",
        "article_contents",
        "article_analyses",
    }.issubset(table_names(db_path))

    with sqlite3.connect(db_path) as conn:
        run_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(runs)").fetchall()
        }
    assert {"lease_owner", "heartbeat_at"}.issubset(run_columns)


def test_initialize_database_closes_connection_handles(tmp_path):
    db_path = tmp_path / "app.db"

    initialize_database(str(db_path))
    db_path.unlink()

    assert not db_path.exists()


def test_initialize_database_migrates_older_schema_columns(tmp_path):
    db_path = tmp_path / "app.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL,
                extraction_model TEXT,
                summary_model TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                error_summary TEXT
            );
            CREATE TABLE run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                event_type TEXT NOT NULL,
                stage TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE watchlist_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                normalized_ticker TEXT NOT NULL UNIQUE,
                company_name TEXT,
                sector TEXT,
                source_upload_id INTEGER,
                created_at TEXT NOT NULL
            );
            CREATE TABLE gmail_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                gmail_message_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                subject TEXT NOT NULL,
                labels_json TEXT NOT NULL,
                source_key TEXT NOT NULL,
                processing_status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE article_contents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_link_id INTEGER NOT NULL,
                fetch_status TEXT NOT NULL,
                final_url TEXT,
                http_status INTEGER,
                title TEXT,
                extracted_text TEXT,
                failure_reason TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE article_analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_link_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                model TEXT,
                summary TEXT NOT NULL,
                stance TEXT NOT NULL,
                confidence REAL NOT NULL,
                supporting_evidence_json TEXT NOT NULL,
                mentioned_tickers_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE ticker_enrichments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                provider TEXT NOT NULL,
                data_type TEXT NOT NULL,
                data_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )

    initialize_database(str(db_path))

    with sqlite3.connect(db_path) as conn:
        assert {"lease_owner", "heartbeat_at"}.issubset(_columns(conn, "runs"))
        assert {"entity_type", "entity_id", "severity", "details_json"}.issubset(
            _columns(conn, "run_events")
        )
        assert {"priority", "notes", "polygon_validation_status", "polygon_reference"}.issubset(
            _columns(conn, "watchlist_items")
        )
        assert {"received_at", "was_unread_at_discovery", "failure_reason"}.issubset(
            _columns(conn, "gmail_messages")
        )
        assert "text_char_count" in _columns(conn, "article_contents")
        assert "raw_response_json" in _columns(conn, "article_analyses")
        assert {"source_url", "status", "failure_reason"}.issubset(
            _columns(conn, "ticker_enrichments")
        )

    repo = RunRepository(str(db_path))
    first_id = repo.save_ticker_enrichment(
        run_id=1,
        ticker="AAPL",
        provider="zacks",
        data_type="rank",
        data={"rating": "Rank #3 Hold"},
    )
    second_id = repo.save_ticker_enrichment(
        run_id=1,
        ticker="AAPL",
        provider="zacks",
        data_type="rank",
        data={"rating": "Rank #2 Buy"},
    )
    enrichments = repo.list_ticker_enrichments(1)

    assert second_id == first_id
    assert len(enrichments) == 1
    assert enrichments[0]["data"] == {"rating": "Rank #2 Buy"}


def test_run_repository_rejects_second_active_run(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    repository = RunRepository(db_path)

    active_run_id = repository.create_run("gpt-extract", "gpt-summary")

    try:
        repository.create_run("other-extract", "other-summary")
    except ActiveRunError as exc:
        assert exc.active_run_id == active_run_id
    else:
        raise AssertionError("Expected ActiveRunError")


def test_run_repository_reconciles_stale_running_run_only_when_explicit(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    repository = RunRepository(db_path)
    stale_run_id = repository.create_run("gpt-extract", "gpt-summary")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET heartbeat_at = datetime('now', '-2 hours') WHERE id = ?",
            (stale_run_id,),
        )
        conn.commit()

    stale_count = repository.reconcile_stale_running_runs()
    new_run_id = repository.create_run("new-extract", "new-summary")

    assert stale_count == 1
    assert repository.get_run(stale_run_id)["status"] == "stale"
    assert repository.get_run(new_run_id)["status"] == "running"


def test_run_repository_does_not_auto_stale_active_run_on_create(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    repository = RunRepository(db_path)
    active_run_id = repository.create_run("gpt-extract", "gpt-summary")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET heartbeat_at = datetime('now', '-2 hours') WHERE id = ?",
            (active_run_id,),
        )
        conn.commit()

    try:
        repository.create_run("new-extract", "new-summary")
    except ActiveRunError as exc:
        assert exc.active_run_id == active_run_id
    else:
        raise AssertionError("Expected ActiveRunError")

    assert repository.get_run(active_run_id)["status"] == "running"


def _columns(conn, table_name):
    return {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
