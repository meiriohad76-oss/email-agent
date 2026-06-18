import sqlite3

from email_article_analyzer.db import initialize_database


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
        "trusted_sources",
        "gmail_messages",
        "article_links",
        "article_contents",
        "article_analyses",
    }.issubset(table_names(db_path))


def test_initialize_database_closes_connection_handles(tmp_path):
    db_path = tmp_path / "app.db"

    initialize_database(str(db_path))
    db_path.unlink()

    assert not db_path.exists()
