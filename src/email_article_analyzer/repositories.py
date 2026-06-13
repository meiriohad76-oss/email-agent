import json
from typing import Any

from email_article_analyzer.db import connect


class RunRepository:
    def __init__(self, database_path: str):
        self.database_path = database_path

    def create_run(
        self,
        extraction_model: str | None,
        summary_model: str | None,
    ) -> int:
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO runs (status, extraction_model, summary_model)
                VALUES (?, ?, ?)
                """,
                ("running", extraction_model, summary_model),
            )
            return int(cursor.lastrowid)

    def add_event(
        self,
        run_id: int | None,
        event_type: str,
        stage: str,
        message: str,
        details: dict[str, Any] | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        severity: str = "info",
    ) -> int:
        details_json = json.dumps(details or {}, sort_keys=True)
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO run_events (
                    run_id, event_type, stage, entity_type, entity_id,
                    severity, message, details_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    event_type,
                    stage,
                    entity_type,
                    entity_id,
                    severity,
                    message,
                    details_json,
                ),
            )
            return int(cursor.lastrowid)

    def get_run(self, run_id: int) -> dict[str, Any]:
        with connect(self.database_path) as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"Run not found: {run_id}")
        return dict(row)

    def list_events(self, run_id: int) -> list[dict[str, Any]]:
        with connect(self.database_path) as conn:
            rows = conn.execute(
                "SELECT * FROM run_events WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def complete_run(self, run_id: int, status: str = "completed") -> None:
        with connect(self.database_path) as conn:
            conn.execute(
                """
                UPDATE runs
                SET status = ?, completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, run_id),
            )

    def discovery_counts(self, run_id: int) -> dict[str, int]:
        with connect(self.database_path) as conn:
            gmail_messages = conn.execute(
                "SELECT COUNT(*) FROM gmail_messages WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
            article_links = conn.execute(
                """
                SELECT COUNT(*)
                FROM article_links
                JOIN gmail_messages ON gmail_messages.id = article_links.gmail_message_id
                WHERE gmail_messages.run_id = ?
                """,
                (run_id,),
            ).fetchone()[0]
        return {"gmail_messages": int(gmail_messages), "article_links": int(article_links)}


class WatchlistRepository:
    def __init__(self, database_path: str):
        self.database_path = database_path

    def create_upload(
        self,
        original_filename: str,
        columns: list[str],
        sample_rows: list[dict[str, str]],
        row_count: int,
    ) -> int:
        details_columns = json.dumps(columns)
        details_sample = json.dumps(sample_rows)
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO watchlist_uploads (
                    original_filename, columns_json, sample_rows_json, row_count
                )
                VALUES (?, ?, ?, ?)
                """,
                (original_filename, details_columns, details_sample, row_count),
            )
            return int(cursor.lastrowid)

    def replace_items(self, upload_id: int, items: list[dict[str, str | None]]) -> None:
        with connect(self.database_path) as conn:
            conn.execute("DELETE FROM watchlist_items")
            conn.executemany(
                """
                INSERT INTO watchlist_items (
                    ticker, normalized_ticker, company_name, sector, priority, notes,
                    source_upload_id, polygon_validation_status, polygon_reference
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item["ticker"],
                        item["normalized_ticker"],
                        item.get("company_name"),
                        item.get("sector"),
                        item.get("priority"),
                        item.get("notes"),
                        upload_id,
                        "valid",
                        item.get("polygon_reference"),
                    )
                    for item in items
                ],
            )

    def list_active_items(self) -> list[dict[str, Any]]:
        with connect(self.database_path) as conn:
            rows = conn.execute(
                "SELECT * FROM watchlist_items ORDER BY normalized_ticker"
            ).fetchall()
        return [dict(row) for row in rows]


class GmailDiscoveryRepository:
    def __init__(self, database_path: str):
        self.database_path = database_path

    def save_message(
        self,
        run_id: int | None,
        gmail_message_id: str,
        thread_id: str,
        sender: str,
        subject: str,
        labels: list[str],
        source_key: str,
        processing_status: str,
        received_at: str | None = None,
        failure_reason: str | None = None,
    ) -> int:
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO gmail_messages (
                    run_id, gmail_message_id, thread_id, sender, subject, received_at,
                    labels_json, source_key, processing_status, failure_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    gmail_message_id,
                    thread_id,
                    sender,
                    subject,
                    received_at,
                    json.dumps(labels),
                    source_key,
                    processing_status,
                    failure_reason,
                ),
            )
            return int(cursor.lastrowid)

    def save_article_link(
        self,
        gmail_message_row_id: int,
        source_key: str,
        raw_url: str,
        normalized_url: str,
        detection_method: str,
        detection_confidence: float,
        heuristic_notes: str | None,
    ) -> int:
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO article_links (
                    gmail_message_id, source_key, raw_url, normalized_url,
                    detection_method, detection_confidence, heuristic_notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    gmail_message_row_id,
                    source_key,
                    raw_url,
                    normalized_url,
                    detection_method,
                    detection_confidence,
                    heuristic_notes,
                ),
            )
            return int(cursor.lastrowid)

    def get_message(self, row_id: int) -> dict[str, Any]:
        with connect(self.database_path) as conn:
            row = conn.execute("SELECT * FROM gmail_messages WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            raise KeyError(f"Gmail message not found: {row_id}")
        return dict(row)

    def get_article_link(self, row_id: int) -> dict[str, Any]:
        with connect(self.database_path) as conn:
            row = conn.execute("SELECT * FROM article_links WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            raise KeyError(f"Article link not found: {row_id}")
        return dict(row)
