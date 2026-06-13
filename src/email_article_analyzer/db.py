from pathlib import Path
import sqlite3


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
"""


def connect(database_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database(database_path: str) -> None:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(str(path)) as conn:
        conn.executescript(SCHEMA)
