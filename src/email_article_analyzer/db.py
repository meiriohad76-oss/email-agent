from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,
    extraction_model TEXT,
    summary_model TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    error_summary TEXT,
    lease_owner TEXT,
    heartbeat_at TEXT
);

CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    event_type TEXT NOT NULL,
    stage TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    severity TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS watchlist_uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_filename TEXT NOT NULL,
    columns_json TEXT NOT NULL,
    sample_rows_json TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS watchlist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    normalized_ticker TEXT NOT NULL UNIQUE,
    company_name TEXT,
    sector TEXT,
    priority TEXT,
    notes TEXT,
    source_upload_id INTEGER,
    polygon_validation_status TEXT NOT NULL,
    polygon_reference TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_upload_id) REFERENCES watchlist_uploads(id)
);

CREATE TABLE IF NOT EXISTS portfolio_lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_upload_id INTEGER NOT NULL,
    row_number INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    normalized_ticker TEXT NOT NULL,
    values_json TEXT NOT NULL,
    polygon_reference TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_upload_id) REFERENCES watchlist_uploads(id)
);

CREATE TABLE IF NOT EXISTS trusted_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    sender_patterns_json TEXT NOT NULL,
    article_domains_json TEXT NOT NULL,
    login_url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS gmail_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    gmail_message_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    received_at TEXT,
    labels_json TEXT NOT NULL,
    was_unread_at_discovery INTEGER NOT NULL DEFAULT 1,
    source_key TEXT NOT NULL,
    processing_status TEXT NOT NULL,
    failure_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS article_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_message_id INTEGER NOT NULL,
    source_key TEXT NOT NULL,
    raw_url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    detection_method TEXT NOT NULL,
    detection_confidence REAL NOT NULL,
    heuristic_notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (gmail_message_id) REFERENCES gmail_messages(id)
);

CREATE TABLE IF NOT EXISTS article_contents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_link_id INTEGER NOT NULL,
    fetch_status TEXT NOT NULL,
    final_url TEXT,
    http_status INTEGER,
    title TEXT,
    extracted_text TEXT,
    text_char_count INTEGER NOT NULL DEFAULT 0,
    failure_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (article_link_id) REFERENCES article_links(id)
);

CREATE TABLE IF NOT EXISTS article_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_link_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    model TEXT,
    summary TEXT NOT NULL,
    stance TEXT NOT NULL,
    confidence REAL NOT NULL,
    supporting_evidence_json TEXT NOT NULL,
    mentioned_tickers_json TEXT NOT NULL,
    raw_response_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (article_link_id) REFERENCES article_links(id)
);

CREATE TABLE IF NOT EXISTS ticker_enrichments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    provider TEXT NOT NULL,
    data_type TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}',
    source_url TEXT,
    status TEXT NOT NULL DEFAULT 'ready',
    failure_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_id, ticker, provider, data_type),
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS report_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
"""


@contextmanager
def connect(database_path: str) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database(database_path: str) -> None:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(str(path)) as conn:
        conn.executescript(SCHEMA)
        _migrate_schema(conn)


def _migrate_schema(conn: sqlite3.Connection) -> None:
    migrations = {
        "runs": [
            ("lease_owner", "TEXT"),
            ("heartbeat_at", "TEXT"),
        ],
        "run_events": [
            ("entity_type", "TEXT"),
            ("entity_id", "TEXT"),
            ("severity", "TEXT NOT NULL DEFAULT 'info'"),
            ("details_json", "TEXT NOT NULL DEFAULT '{}'"),
        ],
        "watchlist_items": [
            ("priority", "TEXT"),
            ("notes", "TEXT"),
            ("polygon_validation_status", "TEXT NOT NULL DEFAULT 'unknown'"),
            ("polygon_reference", "TEXT"),
            ("updated_at", "TEXT"),
        ],
        "gmail_messages": [
            ("received_at", "TEXT"),
            ("was_unread_at_discovery", "INTEGER NOT NULL DEFAULT 1"),
            ("failure_reason", "TEXT"),
            ("updated_at", "TEXT"),
        ],
        "article_contents": [
            ("text_char_count", "INTEGER NOT NULL DEFAULT 0"),
        ],
        "article_analyses": [
            ("raw_response_json", "TEXT NOT NULL DEFAULT '{}'"),
        ],
        "ticker_enrichments": [
            ("source_url", "TEXT"),
            ("status", "TEXT NOT NULL DEFAULT 'ready'"),
            ("failure_reason", "TEXT"),
            ("updated_at", "TEXT"),
        ],
    }
    for table_name, columns in migrations.items():
        _ensure_columns(conn, table_name, columns)
    _deduplicate_ticker_enrichments(conn)
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ticker_enrichments_run_ticker_provider_type
        ON ticker_enrichments (run_id, ticker, provider, data_type)
        """
    )


def _ensure_columns(
    conn: sqlite3.Connection,
    table_name: str,
    columns: list[tuple[str, str]],
) -> None:
    existing_columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for column_name, definition in columns:
        if column_name not in existing_columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _deduplicate_ticker_enrichments(conn: sqlite3.Connection) -> None:
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    if "ticker_enrichments" not in tables:
        return
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(ticker_enrichments)").fetchall()
    }
    if not {"run_id", "ticker", "provider", "data_type"}.issubset(columns):
        return
    conn.execute(
        """
        DELETE FROM ticker_enrichments
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM ticker_enrichments
            GROUP BY run_id, ticker, provider, data_type
        )
        """
    )
