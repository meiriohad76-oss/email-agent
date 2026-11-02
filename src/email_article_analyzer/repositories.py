import json
from uuid import uuid4
from typing import Any

from email_article_analyzer.db import connect
from email_article_analyzer.watchlist import normalize_ticker


RUN_STALE_AFTER_SECONDS = 1800


class ActiveRunError(RuntimeError):
    def __init__(self, active_run_id: int):
        super().__init__(f"Another discovery run is already active: {active_run_id}")
        self.active_run_id = active_run_id


class RunRepository:
    def __init__(self, database_path: str):
        self.database_path = database_path

    def create_run(
        self,
        extraction_model: str | None,
        summary_model: str | None,
    ) -> int:
        lease_owner = str(uuid4())
        with connect(self.database_path) as conn:
            active = conn.execute(
                """
                SELECT id
                FROM runs
                WHERE status = 'running'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            if active is not None:
                raise ActiveRunError(int(active["id"]))
            cursor = conn.execute(
                """
                INSERT INTO runs (
                    status, extraction_model, summary_model, lease_owner, heartbeat_at
                )
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                ("running", extraction_model, summary_model, lease_owner),
            )
            return int(cursor.lastrowid)

    def reconcile_stale_running_runs(self) -> int:
        with connect(self.database_path) as conn:
            return self._mark_stale_runs_locked(conn)

    def heartbeat_run(self, run_id: int) -> bool:
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                UPDATE runs
                SET heartbeat_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'running'
                """,
                (run_id,),
            )
            return cursor.rowcount > 0

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

    def complete_run(
        self,
        run_id: int,
        status: str = "completed",
        error_summary: str | None = None,
    ) -> None:
        with connect(self.database_path) as conn:
            conn.execute(
                """
                UPDATE runs
                SET status = ?,
                    completed_at = CURRENT_TIMESTAMP,
                    error_summary = ?,
                    lease_owner = NULL,
                    heartbeat_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, error_summary, run_id),
            )

    def complete_run_if_running(
        self,
        run_id: int,
        status: str = "completed",
        error_summary: str | None = None,
    ) -> bool:
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                UPDATE runs
                SET status = ?,
                    completed_at = CURRENT_TIMESTAMP,
                    error_summary = ?,
                    lease_owner = NULL,
                    heartbeat_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'running'
                """,
                (status, error_summary, run_id),
            )
            return cursor.rowcount > 0

    def _mark_stale_runs_locked(self, conn) -> int:
        cursor = conn.execute(
            """
            UPDATE runs
            SET status = 'stale',
                completed_at = CURRENT_TIMESTAMP,
                error_summary = 'Run heartbeat expired',
                lease_owner = NULL
            WHERE status = 'running'
              AND (
                heartbeat_at IS NULL
                OR datetime(heartbeat_at, '+' || ? || ' seconds') < CURRENT_TIMESTAMP
              )
            """,
            (RUN_STALE_AFTER_SECONDS,),
        )
        return int(cursor.rowcount)

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

    def gmail_message_ids_for_run(self, run_id: int) -> list[str]:
        with connect(self.database_path) as conn:
            if conn.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone() is None:
                raise KeyError(f"Run not found: {run_id}")
            rows = conn.execute(
                """
                SELECT gmail_message_id
                FROM gmail_messages
                WHERE run_id = ?
                ORDER BY id
                """,
                (run_id,),
            ).fetchall()
        return [str(row["gmail_message_id"]) for row in rows]

    def delete_run(self, run_id: int) -> dict[str, int]:
        with connect(self.database_path) as conn:
            if conn.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone() is None:
                raise KeyError(f"Run not found: {run_id}")
            deleted: dict[str, int] = {}
            cursor = conn.execute(
                "DELETE FROM ticker_enrichments WHERE run_id = ?",
                (run_id,),
            )
            deleted["ticker_enrichments"] = int(cursor.rowcount)
            cursor = conn.execute(
                """
                DELETE FROM article_analyses
                WHERE article_link_id IN (
                    SELECT article_links.id
                    FROM article_links
                    JOIN gmail_messages ON gmail_messages.id = article_links.gmail_message_id
                    WHERE gmail_messages.run_id = ?
                )
                """,
                (run_id,),
            )
            deleted["article_analyses"] = int(cursor.rowcount)
            cursor = conn.execute(
                """
                DELETE FROM article_contents
                WHERE article_link_id IN (
                    SELECT article_links.id
                    FROM article_links
                    JOIN gmail_messages ON gmail_messages.id = article_links.gmail_message_id
                    WHERE gmail_messages.run_id = ?
                )
                """,
                (run_id,),
            )
            deleted["article_contents"] = int(cursor.rowcount)
            cursor = conn.execute(
                """
                DELETE FROM article_links
                WHERE gmail_message_id IN (
                    SELECT id
                    FROM gmail_messages
                    WHERE run_id = ?
                )
                """,
                (run_id,),
            )
            deleted["article_links"] = int(cursor.rowcount)
            cursor = conn.execute(
                "DELETE FROM gmail_messages WHERE run_id = ?",
                (run_id,),
            )
            deleted["gmail_messages"] = int(cursor.rowcount)
            cursor = conn.execute(
                "DELETE FROM run_events WHERE run_id = ?",
                (run_id,),
            )
            deleted["run_events"] = int(cursor.rowcount)
            cursor = conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            deleted["runs"] = int(cursor.rowcount)
        return deleted

    def has_analyzed_gmail_message(self, gmail_message_id: str) -> bool:
        with connect(self.database_path) as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM gmail_messages
                JOIN article_links ON article_links.gmail_message_id = gmail_messages.id
                JOIN article_analyses ON article_analyses.article_link_id = article_links.id
                WHERE gmail_messages.gmail_message_id = ?
                LIMIT 1
                """,
                (gmail_message_id,),
            ).fetchone()
        return row is not None

    def reset_analyzed_state(self) -> int:
        with connect(self.database_path) as conn:
            cursor = conn.execute("DELETE FROM article_analyses")
            return int(cursor.rowcount)

    def save_ticker_enrichment(
        self,
        run_id: int,
        ticker: str,
        provider: str,
        data_type: str,
        data: dict[str, Any],
        source_url: str | None = None,
        status: str = "ready",
        failure_reason: str | None = None,
    ) -> int:
        normalized_ticker = normalize_ticker(ticker)
        if not normalized_ticker:
            raise ValueError("ticker is required")
        data_json = json.dumps(data, sort_keys=True)
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO ticker_enrichments (
                    run_id, ticker, provider, data_type, data_json,
                    source_url, status, failure_reason, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(run_id, ticker, provider, data_type)
                DO UPDATE SET
                    data_json = excluded.data_json,
                    source_url = excluded.source_url,
                    status = excluded.status,
                    failure_reason = excluded.failure_reason,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    run_id,
                    normalized_ticker,
                    provider,
                    data_type,
                    data_json,
                    source_url,
                    status,
                    failure_reason,
                ),
            )
            row = conn.execute(
                """
                SELECT id
                FROM ticker_enrichments
                WHERE run_id = ? AND ticker = ? AND provider = ? AND data_type = ?
                """,
                (run_id, normalized_ticker, provider, data_type),
            ).fetchone()
        return int(row["id"] if row is not None else cursor.lastrowid)

    def list_ticker_enrichments(self, run_id: int) -> list[dict[str, Any]]:
        with connect(self.database_path) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM ticker_enrichments
                WHERE run_id = ?
                ORDER BY ticker, provider, data_type
                """,
                (run_id,),
            ).fetchall()
        enrichments: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["data"] = _json_object(item.pop("data_json"))
            enrichments.append(item)
        return enrichments

    def has_ticker_enrichments(self, run_id: int, ticker: str) -> bool:
        normalized_ticker = normalize_ticker(ticker)
        with connect(self.database_path) as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM ticker_enrichments
                WHERE run_id = ? AND ticker = ?
                LIMIT 1
                """,
                (run_id, normalized_ticker),
            ).fetchone()
        return row is not None

    def has_complete_ticker_enrichments(
        self,
        run_id: int,
        ticker: str,
        required_data_types: set[str] | None = None,
    ) -> bool:
        normalized_ticker = normalize_ticker(ticker)
        with connect(self.database_path) as conn:
            rows = conn.execute(
                """
                SELECT provider, data_type, status
                FROM ticker_enrichments
                WHERE run_id = ? AND ticker = ?
                """,
                (run_id, normalized_ticker),
            ).fetchall()
        if not rows:
            return False
        if required_data_types is None:
            return all(row["status"] in {"ready", "not_applicable"} for row in rows)
        ready_types = set()
        for row in rows:
            if row["status"] not in {"ready", "not_applicable"}:
                continue
            provider = str(row["provider"])
            data_type = str(row["data_type"])
            ready_types.add(data_type)
            ready_types.add(f"{provider}:{data_type}")
        return required_data_types.issubset(ready_types)

    def delete_ticker_enrichment(
        self,
        run_id: int,
        ticker: str,
        provider: str,
        data_type: str,
    ) -> int:
        normalized_ticker = normalize_ticker(ticker)
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                DELETE FROM ticker_enrichments
                WHERE run_id = ? AND ticker = ? AND provider = ? AND data_type = ?
                """,
                (run_id, normalized_ticker, provider, data_type),
            )
        return int(cursor.rowcount)

    def list_discovered_articles(self, run_id: int) -> list[dict[str, Any]]:
        with connect(self.database_path) as conn:
            watchlist_by_ticker = {
                row["normalized_ticker"]: dict(row)
                for row in conn.execute("SELECT * FROM watchlist_items")
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
            self._article_detail_from_row(dict(row), watchlist_by_ticker=watchlist_by_ticker)
            for row in rows
        ]

    def _article_detail_from_row(
        self,
        row: dict[str, Any],
        active_tickers: set[str] | None = None,
        watchlist_by_ticker: dict[str, dict[str, Any]] | None = None,
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
            active_tickers = active_tickers or set(watchlist_by_ticker or {})
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
                "mentioned_ticker_details": _ticker_details(
                    mentioned_tickers,
                    active_tickers=active_tickers,
                    watchlist_by_ticker=watchlist_by_ticker or {},
                ),
                "price_targets": _json_list(raw_response.get("price_targets")),
                "rating_snapshots": _json_list(raw_response.get("rating_snapshots")),
                "actionable_data": _json_list(raw_response.get("actionable_data")),
                "actionable_signals": _json_list(raw_response.get("actionable_signals")),
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

    def replace_portfolio_lots(self, upload_id: int, lots: list[dict[str, Any]]) -> None:
        with connect(self.database_path) as conn:
            conn.execute("DELETE FROM portfolio_lots")
            conn.executemany(
                """
                INSERT INTO portfolio_lots (
                    source_upload_id, row_number, ticker, normalized_ticker,
                    values_json, polygon_reference
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        upload_id,
                        lot["row_number"],
                        lot["ticker"],
                        lot["normalized_ticker"],
                        json.dumps(lot["values"], sort_keys=True),
                        lot.get("polygon_reference"),
                    )
                    for lot in lots
                ],
            )

    def list_active_items(self) -> list[dict[str, Any]]:
        with connect(self.database_path) as conn:
            rows = conn.execute(
                "SELECT * FROM watchlist_items ORDER BY normalized_ticker"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_active_portfolio_lots(self) -> list[dict[str, Any]]:
        with connect(self.database_path) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM portfolio_lots
                ORDER BY row_number, id
                """
            ).fetchall()
        lots = [dict(row) for row in rows]
        for lot in lots:
            lot["values"] = json.loads(lot.pop("values_json") or "{}")
        return lots


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

    def update_message_status_by_gmail_id(
        self,
        gmail_message_id: str,
        processing_status: str,
        failure_reason: str | None = None,
    ) -> int:
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                UPDATE gmail_messages
                SET processing_status = ?,
                    failure_reason = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = (
                    SELECT id
                    FROM gmail_messages
                    WHERE gmail_message_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                )
                """,
                (processing_status, failure_reason, gmail_message_id),
            )
            return int(cursor.rowcount)

    def update_message_status_for_run(
        self,
        run_id: int,
        gmail_message_id: str,
        processing_status: str,
        failure_reason: str | None = None,
    ) -> int:
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                UPDATE gmail_messages
                SET processing_status = ?,
                    failure_reason = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE run_id = ? AND gmail_message_id = ?
                """,
                (processing_status, failure_reason, run_id, gmail_message_id),
            )
            return int(cursor.rowcount)

    def update_message_status(
        self,
        row_id: int,
        processing_status: str,
        failure_reason: str | None = None,
    ) -> int:
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                UPDATE gmail_messages
                SET processing_status = ?,
                    failure_reason = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (processing_status, failure_reason, row_id),
            )
            return int(cursor.rowcount)

    def list_pending_gmail_mark_messages(self, run_id: int) -> list[dict[str, Any]]:
        with connect(self.database_path) as conn:
            rows = conn.execute(
                """
                SELECT id, gmail_message_id, processing_status
                FROM gmail_messages
                WHERE run_id = ?
                  AND processing_status IN (
                    'analyzed_gmail_mark_pending',
                    'failed_gmail_mark_pending'
                  )
                ORDER BY id
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

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


def _ticker_details(
    mentioned_tickers: list[str],
    active_tickers: set[str],
    watchlist_by_ticker: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    details = []
    for ticker in mentioned_tickers:
        normalized = normalize_ticker(str(ticker))
        watchlist_item = watchlist_by_ticker.get(normalized)
        polygon_reference = _json_object(
            watchlist_item.get("polygon_reference") if watchlist_item else None
        )
        detail = {
            "ticker": ticker,
            "in_portfolio": normalized in active_tickers,
        }
        if watchlist_item is not None:
            detail.update(
                {
                    "company_name": watchlist_item.get("company_name") or polygon_reference.get("name"),
                    "sector": watchlist_item.get("sector"),
                    "priority": watchlist_item.get("priority"),
                    "notes": watchlist_item.get("notes"),
                    "polygon_reference": polygon_reference,
                    "asset_type": _asset_type_from_polygon_reference(polygon_reference),
                }
            )
        details.append(detail)
    return details


def _asset_type_from_polygon_reference(reference: dict[str, Any]) -> str | None:
    polygon_type = str(reference.get("type") or "").upper()
    name = str(reference.get("name") or "").lower()
    if polygon_type in {"ETF", "ETN", "FUND"} or "etf" in name:
        return "etf"
    if polygon_type in {"CS", "ADRC", "PFD"}:
        return "stock"
    return polygon_type.lower() or None
