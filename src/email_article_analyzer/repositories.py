import json
from typing import Any

from email_article_analyzer.db import connect
from email_article_analyzer.watchlist import normalize_ticker


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

    def list_recent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        with connect(self.database_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

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

    def list_discovered_articles(self, run_id: int) -> list[dict[str, Any]]:
        with connect(self.database_path) as conn:
            active_tickers = {
                row["normalized_ticker"]
                for row in conn.execute("SELECT normalized_ticker FROM watchlist_items")
            }
            rows = conn.execute(
                """
                SELECT
                    article_links.id AS article_link_id,
                    gmail_messages.gmail_message_id,
                    gmail_messages.sender,
                    gmail_messages.subject,
                    gmail_messages.processing_status AS message_status,
                    article_links.source_key,
                    article_links.normalized_url,
                    article_links.detection_method,
                    article_links.detection_confidence,
                    article_contents.fetch_status,
                    article_contents.title AS content_title,
                    article_contents.text_char_count,
                    article_contents.failure_reason AS content_failure_reason,
                    article_analyses.provider AS analysis_provider,
                    article_analyses.model AS analysis_model,
                    article_analyses.summary AS analysis_summary,
                    article_analyses.stance AS analysis_stance,
                    article_analyses.confidence AS analysis_confidence,
                    article_analyses.supporting_evidence_json,
                    article_analyses.mentioned_tickers_json,
                    article_analyses.raw_response_json
                FROM article_links
                JOIN gmail_messages ON gmail_messages.id = article_links.gmail_message_id
                LEFT JOIN article_contents ON article_contents.id = (
                    SELECT id
                    FROM article_contents
                    WHERE article_contents.article_link_id = article_links.id
                    ORDER BY id DESC
                    LIMIT 1
                )
                LEFT JOIN article_analyses ON article_analyses.id = (
                    SELECT id
                    FROM article_analyses
                    WHERE article_analyses.article_link_id = article_links.id
                    ORDER BY id DESC
                    LIMIT 1
                )
                WHERE gmail_messages.run_id = ?
                ORDER BY article_links.id
                """,
                (run_id,),
            ).fetchall()
        return [
            self._article_detail_from_row(dict(row), active_tickers=active_tickers)
            for row in rows
        ]

    def _article_detail_from_row(
        self,
        row: dict[str, Any],
        active_tickers: set[str] | None = None,
    ) -> dict[str, Any]:
        article = {
            "article_link_id": row["article_link_id"],
            "gmail_message_id": row["gmail_message_id"],
            "sender": row["sender"],
            "subject": row["subject"],
            "message_status": row["message_status"],
            "source_key": row["source_key"],
            "normalized_url": row["normalized_url"],
            "detection_method": row["detection_method"],
            "detection_confidence": row["detection_confidence"],
            "content": None,
            "analysis": None,
        }
        if row["fetch_status"] is not None:
            article["content"] = {
                "fetch_status": row["fetch_status"],
                "title": row["content_title"],
                "text_char_count": row["text_char_count"],
                "failure_reason": row["content_failure_reason"],
            }
        if row["analysis_provider"] is not None:
            mentioned_tickers = json.loads(row["mentioned_tickers_json"])
            raw_response = _json_object(row.get("raw_response_json"))
            article["analysis"] = {
                "provider": row["analysis_provider"],
                "model": row["analysis_model"],
                "summary": row["analysis_summary"],
                "stance": row["analysis_stance"],
                "sentiment": raw_response.get("sentiment", "unclear"),
                "recommendation": raw_response.get("recommendation", "unclear"),
                "confidence": row["analysis_confidence"],
                "supporting_evidence": json.loads(row["supporting_evidence_json"]),
                "mentioned_tickers": mentioned_tickers,
                "mentioned_ticker_details": [
                    {
                        "ticker": ticker,
                        "in_portfolio": normalize_ticker(str(ticker)) in (active_tickers or set()),
                    }
                    for ticker in mentioned_tickers
                ],
                "price_targets": _json_list(raw_response.get("price_targets")),
                "actionable_data": _json_list(raw_response.get("actionable_data")),
            }
        return article


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

    def save_article_content(
        self,
        article_link_id: int,
        fetch_status: str,
        final_url: str | None,
        http_status: int | None,
        title: str | None,
        extracted_text: str | None,
        failure_reason: str | None,
    ) -> int:
        text = extracted_text or ""
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO article_contents (
                    article_link_id, fetch_status, final_url, http_status, title,
                    extracted_text, text_char_count, failure_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article_link_id,
                    fetch_status,
                    final_url,
                    http_status,
                    title,
                    extracted_text,
                    len(text),
                    failure_reason,
                ),
            )
            return int(cursor.lastrowid)

    def get_article_content(self, row_id: int) -> dict[str, Any]:
        with connect(self.database_path) as conn:
            row = conn.execute("SELECT * FROM article_contents WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            raise KeyError(f"Article content not found: {row_id}")
        return dict(row)

    def save_article_analysis(
        self,
        article_link_id: int,
        provider: str,
        model: str | None,
        summary: str,
        stance: str,
        confidence: float,
        supporting_evidence: list[str],
        mentioned_tickers: list[str],
        raw_response: dict[str, Any] | None = None,
    ) -> int:
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO article_analyses (
                    article_link_id, provider, model, summary, stance, confidence,
                    supporting_evidence_json, mentioned_tickers_json, raw_response_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article_link_id,
                    provider,
                    model,
                    summary,
                    stance,
                    confidence,
                    json.dumps(supporting_evidence),
                    json.dumps(mentioned_tickers),
                    json.dumps(raw_response or {}, sort_keys=True),
                ),
            )
            return int(cursor.lastrowid)

    def get_article_analysis(self, row_id: int) -> dict[str, Any]:
        with connect(self.database_path) as conn:
            row = conn.execute("SELECT * FROM article_analyses WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            raise KeyError(f"Article analysis not found: {row_id}")
        return dict(row)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
