from typing import Any
import inspect
import json

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from email_article_analyzer.api.status import missing_essential_providers
from email_article_analyzer.api.status import provider_status
from email_article_analyzer.db_backup import backup_sqlite_database
from email_article_analyzer.db_backup import restore_sqlite_database
from email_article_analyzer.model_defaults import DEFAULT_EXTRACTION_MODEL
from email_article_analyzer.model_defaults import DEFAULT_SUMMARY_MODEL
from email_article_analyzer.model_defaults import normalize_model_name
from email_article_analyzer.gmail import ANALYZED_LABEL
from email_article_analyzer.gmail import FAILED_LABEL
from email_article_analyzer.orchestrator_factory import create_gmail_provider
from email_article_analyzer.rating_enrichment import required_enrichment_data_types
from email_article_analyzer.report_export import build_run_markdown_report
from email_article_analyzer.report_pdf_export import build_run_pdf_report
from email_article_analyzer.repositories import GmailDiscoveryRepository
from email_article_analyzer.repositories import ActiveRunError
from email_article_analyzer.repositories import RunRepository
from email_article_analyzer.repositories import WatchlistRepository
from email_article_analyzer.watchlist import normalize_ticker

router = APIRouter(prefix="/api/runs", tags=["runs"])


class CreateRunRequest(BaseModel):
    extraction_model: str | None = None
    summary_model: str | None = None
    max_new_messages: int | None = Field(default=None, ge=1)

    @field_validator("extraction_model", "summary_model", mode="before")
    @classmethod
    def validate_model_name(cls, value: object) -> object:
        if value is None or isinstance(value, str):
            return value
        raise ValueError("model name must be a string")


@router.post("")
def create_run(payload: CreateRunRequest, request: Request) -> dict[str, Any]:
    readiness = provider_status(request.app.state.config)
    missing_providers = missing_essential_providers(readiness)
    if missing_providers:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Essential providers are not ready",
                "missing_essential_providers": missing_providers,
                "provider_status": readiness,
            },
        )
    orchestrator = getattr(request.app.state, "run_orchestrator", None)
    if orchestrator is None:
        raise HTTPException(
            status_code=503,
            detail="Run orchestrator is not configured",
        )
    browser_task_queue = getattr(request.app.state, "browser_task_queue", None)
    if (
        getattr(request.app.state, "browser_bridge_required_for_runs", False)
        and browser_task_queue is not None
        and not browser_task_queue.is_extension_connected()
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Chrome bridge is not connected",
                "next": (
                    "Reload or enable the Email Article Analyzer Bridge extension, "
                    "then wait for the dashboard to show Chrome bridge connected."
                ),
            },
        )
    run_control = request.app.state.run_control
    repository = RunRepository(request.app.state.database_path)
    if not run_control.begin_run():
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Another discovery run is already active",
                "active_run_id": run_control.active_run_id(),
            },
        )
    try:
        extraction_model = normalize_model_name(
            payload.extraction_model,
            DEFAULT_EXTRACTION_MODEL,
        )
        summary_model = normalize_model_name(
            payload.summary_model,
            DEFAULT_SUMMARY_MODEL,
        )
        start_run = orchestrator.start_discovery_run
        if "on_run_started" in inspect.signature(start_run).parameters:
            try:
                result = start_run(
                    extraction_model=extraction_model,
                    summary_model=summary_model,
                    on_run_started=run_control.set_active_run_id,
                    max_new_messages=payload.max_new_messages,
                )
            except ActiveRunError as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Another discovery run is already active",
                        "active_run_id": exc.active_run_id,
                    },
                ) from exc
        else:
            try:
                result = start_run(
                    extraction_model=extraction_model,
                    summary_model=summary_model,
                )
            except ActiveRunError as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Another discovery run is already active",
                        "active_run_id": exc.active_run_id,
                    },
                ) from exc
            run_control.set_active_run_id(result.run_id)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Discovery run failed",
                "error": str(exc),
            },
        ) from exc
    finally:
        run_control.end_run()
    return {
        "run_id": result.run_id,
        "status": result.status,
        "candidate_count": result.candidate_count,
        "needed_source_logins": result.needed_source_logins,
        "alerts": _run_alerts(repository=RunRepository(request.app.state.database_path), run_id=result.run_id),
    }


@router.post("/stop-current")
def stop_current_run(request: Request) -> dict[str, str]:
    request.app.state.run_control.request_stop()
    return {
        "status": "stop_requested",
        "message": "Current run will stop after the active article finishes.",
    }


@router.post("/{run_id}/force-stop")
def force_stop_run(run_id: int, request: Request) -> dict[str, Any]:
    repository = RunRepository(request.app.state.database_path)
    try:
        run = repository.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    if run["status"] != "running":
        return {
            "run_id": run_id,
            "status": run["status"],
            "message": "Run is not running.",
        }
    if request.app.state.run_control.active_run_id() == run_id:
        request.app.state.run_control.request_stop()
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Run is active; cooperative stop was requested instead.",
                "run_id": run_id,
            },
        )
    if not repository.complete_run_if_running(run_id, status="stopped"):
        run = repository.get_run(run_id)
        return {
            "run_id": run_id,
            "status": run["status"],
            "message": "Run status changed before force-stop could be applied.",
        }
    repository.add_event(
        run_id=run_id,
        event_type="run_force_stopped",
        stage="control",
        message="Run was marked stopped after no active worker progress was observed",
        severity="warning",
    )
    return {
        "run_id": run_id,
        "status": "stopped",
        "message": "Run marked stopped.",
    }


@router.post("/{run_id}/retry-enrichments")
def retry_run_enrichments(
    run_id: int,
    request: Request,
    ticker: str | None = None,
    force: bool = False,
    allow_unlisted: bool = False,
) -> dict[str, Any]:
    bulk_manager = getattr(request.app.state, "bulk_research_extraction", None)
    if bulk_manager is not None and bulk_manager.status()["status"] in {"running", "stopping"}:
        raise HTTPException(
            status_code=409,
            detail="Bulk research extraction is active; stop it before starting an individual retry",
        )
    repository = RunRepository(request.app.state.database_path)
    try:
        repository.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc

    rating_enricher = getattr(
        getattr(request.app.state, "run_orchestrator", None),
        "rating_enricher",
        None,
    )
    if rating_enricher is None:
        raise HTTPException(status_code=503, detail="Rating enricher is not configured")

    articles = repository.list_discovered_articles(run_id)
    results = []
    active_watchlist_items = _active_watchlist_items(request.app.state.database_path)
    active_watchlist_tickers = set(active_watchlist_items)
    tickers = _portfolio_tickers_for_articles(articles, active_watchlist_tickers)
    if allow_unlisted and (not ticker or not force):
        raise HTTPException(
            status_code=400,
            detail="allow_unlisted requires one explicit ticker and force=true",
        )
    if ticker:
        requested_ticker = normalize_ticker(ticker)
        tickers = (
            {requested_ticker}
            if requested_ticker in active_watchlist_tickers or allow_unlisted
            else set()
        )
    for ticker in sorted(tickers):
        asset_type = active_watchlist_items.get(ticker, {}).get("asset_type")
        required_data_types = required_enrichment_data_types(
            asset_type=asset_type,
            include_polygon=getattr(rating_enricher, "polygon_client", None) is not None,
            include_research=getattr(rating_enricher, "include_research", False),
            include_investing=getattr(rating_enricher, "include_research", False),
        )
        if not force and repository.has_complete_ticker_enrichments(
            run_id,
            ticker,
            required_data_types=required_data_types,
        ):
            results.append(
                {
                    "ticker": ticker,
                    "status": "reused",
                    "attempted": 0,
                    "saved": 0,
                    "failed": 0,
                }
            )
            continue
        try:
            result = _call_enrich_ticker(
                rating_enricher,
                run_id=run_id,
                ticker=ticker,
                asset_type=asset_type,
                company_name=active_watchlist_items.get(ticker, {}).get("company_name"),
            )
        except Exception as exc:
            repository.add_event(
                run_id=run_id,
                event_type="ticker_rating_enrichment_failed",
                stage="ticker_enrichment",
                message="Ticker rating enrichment retry failed",
                entity_type="ticker",
                entity_id=ticker,
                severity="warning",
                details={"failure_reason": str(exc)},
            )
            results.append({"ticker": ticker, "attempted": 0, "saved": 0, "failed": 1})
            continue
        repository.add_event(
            run_id=run_id,
            event_type="ticker_rating_enriched",
            stage="ticker_enrichment",
            message="Ticker rating enrichment retry completed",
            entity_type="ticker",
            entity_id=ticker,
            details=result,
        )
        results.append({"ticker": ticker, **result})
    return {
        "status": "completed",
        "run_id": run_id,
        "results": results,
        "ticker_enrichments": repository.list_ticker_enrichments(run_id),
    }


@router.post("/{run_id}/retry-gmail-marks")
def retry_run_gmail_marks(run_id: int, request: Request) -> dict[str, Any]:
    run_repository = RunRepository(request.app.state.database_path)
    try:
        run_repository.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc

    gmail_repository = GmailDiscoveryRepository(request.app.state.database_path)
    pending_messages = gmail_repository.list_pending_gmail_mark_messages(run_id)
    if not pending_messages:
        return {
            "status": "completed",
            "run_id": run_id,
            "retried": 0,
            "repaired": 0,
            "failed": 0,
            "results": [],
        }

    provider = create_gmail_provider(request.app.state.config)
    if provider is None:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Gmail provider is not configured",
                "run_id": run_id,
            },
        )

    results = []
    repaired = 0
    failed = 0
    for message in pending_messages:
        try:
            final_status = _retry_gmail_mark_for_message(
                provider=provider,
                gmail_message_id=message["gmail_message_id"],
                processing_status=message["processing_status"],
            )
        except Exception as exc:
            failed += 1
            failure_reason = str(exc)
            gmail_repository.update_message_status(
                row_id=message["id"],
                processing_status=message["processing_status"],
                failure_reason=failure_reason,
            )
            results.append(
                {
                    "gmail_message_id": message["gmail_message_id"],
                    "status": "failed",
                    "failure_reason": failure_reason,
                }
            )
            continue
        repaired += 1
        gmail_repository.update_message_status(
            row_id=message["id"],
            processing_status=final_status,
            failure_reason=None,
        )
        results.append(
            {
                "gmail_message_id": message["gmail_message_id"],
                "status": "repaired",
                "processing_status": final_status,
            }
        )

    run_repository.add_event(
        run_id=run_id,
        event_type="gmail_marks_retry_completed",
        stage="gmail_discovery",
        message="Pending Gmail marks were retried",
        details={
            "retried": len(pending_messages),
            "repaired": repaired,
            "failed": failed,
        },
    )
    return {
        "status": "completed",
        "run_id": run_id,
        "retried": len(pending_messages),
        "repaired": repaired,
        "failed": failed,
        "results": results,
    }


@router.get("")
def list_runs(request: Request) -> dict[str, Any]:
    repository = RunRepository(request.app.state.database_path)
    runs = [
        {
            **run,
            "counts": repository.discovery_counts(run["id"]),
            "alerts": _run_alerts(repository=repository, run_id=run["id"]),
        }
        for run in repository.list_recent_runs()
    ]
    return {
        "runs": runs,
        "alerts": _history_alerts(
            database_path=request.app.state.database_path,
            runs=runs,
        ),
    }


@router.get("/{run_id}/report.md")
def export_run_report(run_id: int, request: Request) -> Response:
    repository = RunRepository(request.app.state.database_path)
    try:
        run = repository.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    markdown = build_run_markdown_report(
        run=run,
        counts=repository.discovery_counts(run_id),
        events=repository.list_events(run_id),
        articles=repository.list_discovered_articles(run_id),
    )
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="email-article-run-{run_id}-report.md"',
        },
    )


@router.get("/{run_id}/report.pdf")
def export_run_pdf_report(run_id: int, request: Request) -> Response:
    repository = RunRepository(request.app.state.database_path)
    try:
        run = repository.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    articles = repository.list_discovered_articles(run_id)
    pdf = build_run_pdf_report(
        run=run,
        counts=repository.discovery_counts(run_id),
        events=repository.list_events(run_id),
        articles=articles,
        market_data_by_ticker=_market_data_for_report(
            repository,
            run_id,
        ),
        rating_data_by_ticker=_rating_data_for_report(repository, run_id),
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="email-article-run-{run_id}-report.pdf"',
        },
    )


def _retry_gmail_mark_for_message(
    provider,
    gmail_message_id: str,
    processing_status: str,
) -> str:
    if processing_status == "analyzed_gmail_mark_pending":
        marker = getattr(provider, "mark_analyzed", None)
        if callable(marker):
            marker(gmail_message_id, analyzed_label=ANALYZED_LABEL, failed_label=FAILED_LABEL)
            return "analyzed"
        provider.mark_read(gmail_message_id)
        provider.add_label(gmail_message_id, ANALYZED_LABEL)
        provider.remove_label(gmail_message_id, FAILED_LABEL)
        return "analyzed"
    if processing_status == "failed_gmail_mark_pending":
        marker = getattr(provider, "mark_failed", None)
        if callable(marker):
            marker(gmail_message_id, failed_label=FAILED_LABEL)
            return "failed"
        provider.add_label(gmail_message_id, FAILED_LABEL)
        return "failed"
    raise ValueError(f"Unsupported pending Gmail mark status: {processing_status}")


def _market_data_for_report(
    repository: RunRepository,
    run_id: int,
) -> dict[str, dict[str, Any]]:
    market_data: dict[str, dict[str, Any]] = {}
    for enrichment in repository.list_ticker_enrichments(run_id):
        if (
            enrichment["provider"] == "polygon"
            and enrichment["data_type"] == "previous_close"
            and enrichment["status"] == "ready"
        ):
            market_data[enrichment["ticker"]] = enrichment["data"]
    return market_data


def _portfolio_tickers_for_articles(
    articles: list[dict[str, Any]],
    active_watchlist_tickers: set[str] | None = None,
) -> set[str]:
    active_watchlist_tickers = active_watchlist_tickers or set()
    tickers: set[str] = set()
    for article in articles:
        analysis = article.get("analysis") or {}
        specific_tickers: set[str] = set()
        for collection_name in ("actionable_data", "actionable_signals", "price_targets", "rating_snapshots"):
            for item in analysis.get(collection_name) or []:
                normalized = normalize_ticker(str(item.get("ticker") or ""))
                if normalized and normalized in active_watchlist_tickers:
                    specific_tickers.add(normalized)
        if specific_tickers:
            tickers.update(specific_tickers)
            continue
        for detail in analysis.get("mentioned_ticker_details") or []:
            normalized = normalize_ticker(str(detail.get("ticker") or ""))
            if normalized and detail.get("in_portfolio") and normalized in active_watchlist_tickers:
                tickers.add(normalized)
    return tickers


def _active_watchlist_tickers(database_path: str) -> set[str]:
    return set(_active_watchlist_items(database_path))


def _active_watchlist_items(database_path: str) -> dict[str, dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    for item in WatchlistRepository(database_path).list_active_items():
        normalized = normalize_ticker(str(item.get("normalized_ticker") or item.get("ticker") or ""))
        if not normalized:
            continue
        reference = _json_object(item.get("polygon_reference"))
        items[normalized] = {
            "asset_type": _asset_type_from_polygon_reference(reference),
            "polygon_reference": reference,
            "company_name": item.get("company_name") or reference.get("name"),
        }
    return items


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _asset_type_from_polygon_reference(reference: dict[str, Any]) -> str | None:
    polygon_type = str(reference.get("type") or "").upper()
    name = str(reference.get("name") or "").lower()
    if polygon_type in {"ETF", "ETN", "FUND"} or "etf" in name:
        return "etf"
    if polygon_type in {"CS", "ADRC", "PFD"}:
        return "stock"
    return polygon_type.lower() or None


def _call_enrich_ticker(
    enricher,
    run_id: int,
    ticker: str,
    asset_type: str | None,
    company_name: str | None = None,
):
    method = enricher.enrich_ticker
    parameters = inspect.signature(method).parameters
    kwargs = {"run_id": run_id, "ticker": ticker}
    if "asset_type" in parameters:
        kwargs["asset_type"] = asset_type
    if "company_name" in parameters:
        kwargs["company_name"] = company_name
    if len(kwargs) > 2:
        return method(**kwargs)
    return method(run_id=run_id, ticker=ticker)


def _rating_data_for_report(
    repository: RunRepository,
    run_id: int,
) -> dict[str, list[dict[str, Any]]]:
    rating_data: dict[str, list[dict[str, Any]]] = {}
    for enrichment in repository.list_ticker_enrichments(run_id):
        if enrichment["provider"] == "polygon":
            continue
        data = dict(enrichment["data"] or {})
        if enrichment["status"] != "ready":
            data = {
                "ticker": enrichment["ticker"],
                "provider": enrichment["provider"],
                "rating_type": _semantic_rating_type(
                    enrichment["provider"],
                    enrichment["data_type"],
                ),
                "status": enrichment["status"],
                "failure_reason": enrichment["failure_reason"],
            }
        elif not data.get("rating_type"):
            continue
        ticker = normalize_ticker(str(data.get("ticker") or enrichment["ticker"]))
        if not ticker:
            continue
        rating_data.setdefault(ticker, []).append(data)
    return rating_data


def _semantic_rating_type(provider: str, data_type: str) -> str:
    mappings = {
        ("seeking_alpha", "ratings"): "quant",
        ("seeking_alpha", "author_ratings"): "analysts",
        ("seeking_alpha", "sell_side_ratings"): "wall_street",
        ("zacks", "quote"): "rank",
        ("zacks", "price_target_forecast"): "price_target",
    }
    return mappings.get((provider, data_type), data_type)


@router.delete("/{run_id}")
def delete_run(run_id: int, request: Request) -> dict[str, Any]:
    repository = RunRepository(request.app.state.database_path)
    try:
        run = repository.get_run(run_id)
        gmail_message_ids = repository.gmail_message_ids_for_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    if run["status"] == "running" or request.app.state.run_control.active_run_id() == run_id:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Cannot delete a running run. Stop it first and wait for it to finish.",
                "run_id": run_id,
            },
        )

    gmail_reset_count = 0
    try:
        backup_path = backup_sqlite_database(
            request.app.state.database_path,
            reason=f"before-delete-run-{run_id}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Database backup failed; Gmail and DB data were not changed",
                "error": str(exc),
                "run_id": run_id,
            },
        ) from exc
    if gmail_message_ids:
        provider = create_gmail_provider(request.app.state.config)
        if provider is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "Gmail provider is not configured; database was not changed",
                    "run_id": run_id,
                    "database_backup_path": backup_path,
                },
            )
        try:
            gmail_reset_count = provider.reset_processing_labels_for_messages(
                message_ids=gmail_message_ids,
                label_names=[ANALYZED_LABEL, FAILED_LABEL],
                mark_unread=True,
            )
        except Exception as exc:
            partial_reset_count = int(getattr(exc, "reset_count", 0) or 0)
            total_reset_count = getattr(exc, "total_count", len(gmail_message_ids))
            raise HTTPException(
                status_code=502,
                detail={
                    "message": (
                        "Gmail flag reset partially failed; database was not changed, "
                        "but some Gmail labels may already have been reset"
                        if partial_reset_count
                        else "Gmail flag reset failed; database was not changed"
                    ),
                    "error": str(exc),
                    "run_id": run_id,
                    "gmail_reset_count": partial_reset_count,
                    "gmail_reset_total": total_reset_count,
                    "database_backup_path": backup_path,
                },
            ) from exc
    try:
        deleted = repository.delete_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    except Exception as exc:
        restore_sqlite_database(request.app.state.database_path, backup_path)
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Database delete failed after Gmail reset; database was restored from backup",
                "error": str(exc),
                "run_id": run_id,
                "database_backup_path": backup_path,
            },
        ) from exc
    return {
        "status": "deleted",
        "run_id": run_id,
        "gmail_reset_count": gmail_reset_count,
        "database_backup_path": backup_path,
        "deleted": deleted,
    }


@router.get("/{run_id}")
def get_run(run_id: int, request: Request) -> dict[str, Any]:
    repository = RunRepository(request.app.state.database_path)
    try:
        run = repository.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    events = repository.list_events(run_id)
    return {
        "run": run,
        "counts": repository.discovery_counts(run_id),
        "alerts": _alerts_from_events(events),
        "events": events,
        "articles": repository.list_discovered_articles(run_id),
        "ticker_enrichments": repository.list_ticker_enrichments(run_id),
    }


def _run_alerts(repository: RunRepository, run_id: int) -> list[dict[str, Any]]:
    return _alerts_from_events(repository.list_events(run_id))


def _history_alerts(database_path: str, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if runs:
        return []
    watchlist_count = len(WatchlistRepository(database_path).list_active_items())
    if watchlist_count == 0:
        return []
    return [
        {
            "type": "run_history_empty_with_watchlist",
            "severity": "warning",
            "title": "Run history is empty",
            "message": (
                f"The database has {watchlist_count} active watchlist item(s), but no run history. "
                "If this was not intentional, check recent delete/reset actions or restore from backup."
            ),
            "next": "Start a new run only after confirming the missing history is expected.",
        }
    ]


def _alerts_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alerts = []
    if any(_event_is_openai_quota_blocked(event) for event in events):
        alerts.append(
            {
                "type": "openai_quota_depleted",
                "severity": "error",
                "title": "OpenAI credits or quota appear depleted",
                "message": (
                    "OpenAI returned an insufficient quota error. This usually means the API key's "
                    "project has no available credits, billing is not active, or the project quota "
                    "has been reached. Add credits or update billing in OpenAI, then start a new run."
                ),
                "next": "Check OpenAI billing/project limits and re-run after the API key has quota.",
            }
        )
    return alerts


def _event_is_openai_quota_blocked(event: dict[str, Any]) -> bool:
    if event.get("event_type") != "candidate_processing_failed":
        return False
    details = _event_details(event)
    haystack = " ".join(
        str(value)
        for value in (
            event.get("message"),
            details.get("failure_reason"),
            details.get("error"),
        )
        if value
    ).lower()
    quota_markers = (
        "insufficient_quota",
        "you exceeded your current quota",
        "check your plan and billing",
    )
    return any(marker in haystack for marker in quota_markers)


def _event_details(event: dict[str, Any]) -> dict[str, Any]:
    details = event.get("details")
    if isinstance(details, dict):
        return details
    details_json = event.get("details_json")
    if not details_json:
        return {}
    try:
        import json

        parsed = json.loads(details_json)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}
