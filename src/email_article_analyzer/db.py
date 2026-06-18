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
    error_summary TEXT
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
