from dataclasses import dataclass
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import inspect
import json

from email_article_analyzer.article_analysis import ArticleAnalyzer
from email_article_analyzer.article_analysis import ArticlePrechecker
from email_article_analyzer.article_analysis import RunReportSynthesizer
from email_article_analyzer.article_content import (
    ArticleContentFetcherProtocol,
    extract_readable_text_from_html,
)
from email_article_analyzer.gmail import GmailCandidate
from email_article_analyzer.model_defaults import DEFAULT_EXTRACTION_MODEL
from email_article_analyzer.model_defaults import DEFAULT_REPORT_MODEL
from email_article_analyzer.model_defaults import DEFAULT_SUMMARY_MODEL
from email_article_analyzer.model_defaults import normalize_model_name
from email_article_analyzer.repositories import GmailDiscoveryRepository, RunRepository
from email_article_analyzer.repositories import WatchlistRepository
from email_article_analyzer.rating_enrichment import required_enrichment_data_types
from email_article_analyzer.watchlist import normalize_ticker


@dataclass(frozen=True)
class RunResult:
    run_id: int
    status: str
    candidate_count: int
    needed_source_logins: list[str]


class RunOrchestrator:
    def __init__(
        self,
        run_repository: RunRepository,
        gmail_repository: GmailDiscoveryRepository,
        discovery_service,
        article_analyzer: ArticleAnalyzer | None = None,
        article_prechecker: ArticlePrechecker | None = None,
        article_content_fetcher: ArticleContentFetcherProtocol | None = None,
        report_synthesizer: RunReportSynthesizer | None = None,
        rating_enricher=None,
        stop_requested=None,
        gmail_mark_timeout_seconds: float = 10.0,
    ):
        self.run_repository = run_repository
        self.gmail_repository = gmail_repository
        self.discovery_service = discovery_service
        self.article_analyzer = article_analyzer
        self.article_prechecker = article_prechecker
        self.article_content_fetcher = article_content_fetcher
        self.report_synthesizer = report_synthesizer
        self.rating_enricher = rating_enricher
        self.stop_requested = stop_requested or (lambda: False)
        self.gmail_mark_timeout_seconds = gmail_mark_timeout_seconds

    def start_discovery_run(
        self,
        extraction_model: str | None,
        summary_model: str | None,
        on_run_started=None,
        max_new_messages: int | None = None,
    ) -> RunResult:
        extraction_model = normalize_model_name(
            extraction_model,
            DEFAULT_EXTRACTION_MODEL,
        )
        summary_model = normalize_model_name(
            summary_model,
            DEFAULT_SUMMARY_MODEL,
        )
        run_id = self.run_repository.create_run(
            extraction_model=extraction_model,
            summary_model=summary_model,
        )
        processed_count = 0
        stopped = False
        needed_source_logins: set[str] = set()
        discovered_count = 0
        enriched_tickers: set[str] = set()
        if callable(on_run_started):
            on_run_started(run_id)
        try:
            self.run_repository.heartbeat_run(run_id)
            self.run_repository.add_event(
                run_id=run_id,
                event_type="run_started",
                stage="startup",
                message="Run started",
                details={
                    "extraction_model": extraction_model,
                    "summary_model": summary_model,
                    "report_model": DEFAULT_REPORT_MODEL,
                },
            )
            self.run_repository.add_event(
                run_id=run_id,
                event_type="gmail_search_started",
                stage="gmail_discovery",
                message="Gmail discovery started",
            )

            candidates = self._candidate_iterator()
            candidate_iterator = iter(candidates)
            while True:
                if self.stop_requested():
                    stopped = True
                    self.run_repository.add_event(
                        run_id=run_id,
                        event_type="run_stop_requested",
                        stage="control",
                        message="Stop requested; no more candidates will be started",
                        severity="warning",
                        details={
                            "processed_count": processed_count,
                            "candidate_count": discovered_count,
                        },
                    )
                    break
                if max_new_messages is not None and processed_count >= max_new_messages:
                    self.run_repository.add_event(
                        run_id=run_id,
                        event_type="run_message_cap_reached",
                        stage="control",
                        message="Per-run message cap reached; remaining unread emails wait for the next run",
                        details={"max_new_messages": max_new_messages, "processed_count": processed_count},
                    )
                    break
                try:
                    candidate = next(candidate_iterator)
                except StopIteration:
                    break
                self.run_repository.heartbeat_run(run_id)
                discovered_count += 1
                if self.run_repository.has_analyzed_gmail_message(candidate.message.message_id):
                    self._mark_gmail_success(run_id, candidate.message.message_id)
                    self.run_repository.add_event(
                        run_id=run_id,
                        event_type="candidate_already_analyzed",
                        stage="gmail_discovery",
                        message="Gmail message was already analyzed in an earlier run; marked and skipped",
                        entity_type="gmail_message",
                        entity_id=candidate.message.message_id,
                        details={
                            "source_key": candidate.source.source_key,
                            "url": candidate.headline_link.url,
                        },
                    )
                    continue
                try:
                    needs_source_login = self._persist_candidate(
                        run_id,
                        candidate,
                        extraction_model,
                        summary_model,
                    )
                except Exception as exc:
                    quota_exhausted = _is_openai_quota_error(exc)
                    self.run_repository.add_event(
                        run_id=run_id,
                        event_type="candidate_processing_failed",
                        stage="article_analysis",
                        message=(
                            "OpenAI quota exhausted; stopping run"
                            if quota_exhausted
                            else "Candidate processing failed; continuing run"
                        ),
                        entity_type="gmail_message",
                        entity_id=candidate.message.message_id,
                        severity="warning",
                        details={
                            "source_key": candidate.source.source_key,
                            "url": candidate.headline_link.url,
                            "failure_reason": str(exc),
                        },
                    )
                    if quota_exhausted:
                        self.gmail_repository.update_message_status_for_run(
                            run_id=run_id,
                            gmail_message_id=candidate.message.message_id,
                            processing_status="analysis_api_blocked",
                            failure_reason=str(exc),
                        )
                        stopped = True
                        break
                    self._mark_gmail_failure(run_id, candidate.message.message_id)
                    processed_count += 1
                    continue

                if needs_source_login:
                    needed_source_logins.add(candidate.source.source_key)
                self._try_enrich_portfolio_tickers(
                    run_id,
                    enriched_tickers,
                    respect_stop=False,
                )
                self.run_repository.heartbeat_run(run_id)
                self._mark_gmail_success(run_id, candidate.message.message_id)
                processed_count += 1

            final_status = "stopped" if stopped else "completed"
            if final_status == "completed":
                self.run_repository.heartbeat_run(run_id)
                self._try_enrich_portfolio_tickers(run_id, enriched_tickers)
                self._try_synthesize_run_report(run_id, DEFAULT_REPORT_MODEL)
            completed_by_worker = self.run_repository.complete_run_if_running(run_id, status=final_status)
            if not completed_by_worker:
                current_run = self.run_repository.get_run(run_id)
                self.run_repository.add_event(
                    run_id=run_id,
                    event_type="run_completion_skipped",
                    stage="completion",
                    message="Run worker reached completion after DB status had already changed",
                    severity="warning",
                    details={
                        "worker_status": final_status,
                        "database_status": current_run.get("status"),
                        "candidate_count": discovered_count,
                        "processed_count": processed_count,
                    },
                )
                return RunResult(
                    run_id=run_id,
                    status=str(current_run.get("status") or final_status),
                    candidate_count=processed_count,
                    needed_source_logins=sorted(needed_source_logins),
                )
            self.run_repository.add_event(
                run_id=run_id,
                event_type="run_stopped" if stopped else "run_completed",
                stage="completion",
                message="Run stopped" if stopped else "Run completed",
                details={
                    "candidate_count": discovered_count,
                    "processed_count": processed_count,
                },
            )
            return RunResult(
                run_id=run_id,
                status=final_status,
                candidate_count=processed_count,
                needed_source_logins=sorted(needed_source_logins),
            )
        except Exception as exc:
            self.run_repository.add_event(
                run_id=run_id,
                event_type="run_failed",
                stage="completion",
                message="Run failed before reaching normal completion",
                severity="error",
                details={
                    "candidate_count": discovered_count,
                    "processed_count": processed_count,
                    "failure_reason": str(exc),
                },
            )
            self.run_repository.complete_run_if_running(
                run_id,
                status="failed",
                error_summary=str(exc),
            )
            return RunResult(
                run_id=run_id,
                status="failed",
                candidate_count=processed_count,
                needed_source_logins=sorted(needed_source_logins),
            )
        finally:
            self._close_article_content_fetcher()

    def _candidate_iterator(self):
        iterator = getattr(self.discovery_service, "iter_candidates", None)
        if iterator is not None:
            return iterator()
        return iter(self.discovery_service.discover_candidates())

    def _mark_gmail_success(self, run_id: int, message_id: str) -> None:
        self.gmail_repository.update_message_status_for_run(
            run_id=run_id,
            gmail_message_id=message_id,
            processing_status="analyzed_gmail_mark_pending",
            failure_reason=None,
        )
        mark_status = self._run_gmail_mark_with_timeout(
            run_id=run_id,
            event_type="gmail_mark_success_timeout",
            message="Gmail success marker timed out; continuing run",
            message_id=message_id,
            action=lambda: self.discovery_service.mark_success(message_id),
        )
        if mark_status == "success":
            self.gmail_repository.update_message_status_for_run(
                run_id=run_id,
                gmail_message_id=message_id,
                processing_status="analyzed",
                failure_reason=None,
            )
        elif mark_status == "timeout":
            self.gmail_repository.update_message_status_for_run(
                run_id=run_id,
                gmail_message_id=message_id,
                processing_status="analyzed_gmail_mark_pending",
                failure_reason="Gmail success marker timed out",
            )
        else:
            self.gmail_repository.update_message_status_for_run(
                run_id=run_id,
                gmail_message_id=message_id,
                processing_status="analyzed_gmail_mark_pending",
                failure_reason="Gmail success marker failed",
            )

    def _mark_gmail_failure(self, run_id: int, message_id: str) -> None:
        self.gmail_repository.update_message_status_for_run(
            run_id=run_id,
            gmail_message_id=message_id,
            processing_status="failed_gmail_mark_pending",
            failure_reason=None,
        )
        mark_status = self._run_gmail_mark_with_timeout(
            run_id=run_id,
            event_type="gmail_mark_failure_timeout",
            message="Gmail failure marker timed out; continuing run",
            message_id=message_id,
            action=lambda: self.discovery_service.mark_failure(message_id),
        )
        if mark_status == "success":
            self.gmail_repository.update_message_status_for_run(
                run_id=run_id,
                gmail_message_id=message_id,
                processing_status="failed",
                failure_reason=None,
            )
        elif mark_status == "timeout":
            self.gmail_repository.update_message_status_for_run(
                run_id=run_id,
                gmail_message_id=message_id,
                processing_status="failed_gmail_mark_pending",
                failure_reason="Gmail failure marker timed out",
            )
        else:
            self.gmail_repository.update_message_status_for_run(
                run_id=run_id,
                gmail_message_id=message_id,
                processing_status="failed_gmail_mark_pending",
                failure_reason="Gmail failure marker failed",
            )

    def _run_gmail_mark_with_timeout(
        self,
        run_id: int,
        event_type: str,
        message: str,
        message_id: str,
        action,
    ) -> str:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(action)
        try:
            future.result(timeout=self.gmail_mark_timeout_seconds)
            return "success"
        except FutureTimeoutError:
            self.run_repository.add_event(
                run_id=run_id,
                event_type=event_type,
                stage="gmail_discovery",
                message=message,
                entity_type="gmail_message",
                entity_id=message_id,
                severity="warning",
                details={"timeout_seconds": self.gmail_mark_timeout_seconds},
            )
            future.cancel()
            return "timeout"
        except Exception as exc:
            self.run_repository.add_event(
                run_id=run_id,
                event_type=event_type.replace("_timeout", "_failed"),
                stage="gmail_discovery",
                message=message.replace("timed out", "failed"),
                entity_type="gmail_message",
                entity_id=message_id,
                severity="warning",
                details={"failure_reason": str(exc)},
            )
            return "failed"
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _close_article_content_fetcher(self) -> None:
        if self.article_content_fetcher is None:
            return
        closer = getattr(self.article_content_fetcher, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass

    def _persist_candidate(
        self,
        run_id: int,
        candidate: GmailCandidate,
        extraction_model: str,
        summary_model: str,
    ) -> bool:
        needs_source_login = False
        message = candidate.message
        message_row_id = self.gmail_repository.save_message(
            run_id=run_id,
            gmail_message_id=message.message_id,
            thread_id=message.thread_id,
            sender=message.sender,
            subject=message.subject,
            labels=message.labels,
            source_key=candidate.source.source_key,
            processing_status="discovered",
            received_at=_format_gmail_internal_date(message.internal_date_ms),
        )
        article_link_id = self.gmail_repository.save_article_link(
            gmail_message_row_id=message_row_id,
            source_key=candidate.source.source_key,
            raw_url=candidate.headline_link.url,
            normalized_url=candidate.headline_link.url,
            detection_method=candidate.headline_link.detection_method,
            detection_confidence=candidate.headline_link.detection_confidence,
            heuristic_notes=None,
        )
        self.run_repository.add_event(
            run_id=run_id,
            event_type="headline_link_detected",
            stage="gmail_discovery",
            message="Headline link detected",
            entity_type="gmail_message",
            entity_id=message.message_id,
            details={
                "source_key": candidate.source.source_key,
                "url": candidate.headline_link.url,
                "detection_method": candidate.headline_link.detection_method,
            },
        )
        if self.article_analyzer is None:
            return needs_source_login

        article_title = None
        article_text = None
        if self.article_content_fetcher is not None:
            try:
                content = self.article_content_fetcher.fetch(candidate.headline_link.url)
            except Exception as exc:
                needs_source_login = True
                failure_reason = str(exc)
                failure_details = {
                    "failure_stage": getattr(exc, "stage", "unknown"),
                    **getattr(exc, "details", {}),
                }
                if failure_details.get("skip_analysis"):
                    content_id = self.gmail_repository.save_article_content(
                        article_link_id=article_link_id,
                        fetch_status="blocked",
                        final_url=candidate.headline_link.url,
                        http_status=None,
                        title=failure_details.get("page_title"),
                        extracted_text=None,
                        failure_reason=failure_reason,
                    )
                    self.run_repository.add_event(
                        run_id=run_id,
                        event_type="article_content_blocked",
                        stage="article_content",
                        message="Article content blocked by source verification; analysis skipped",
                        entity_type="article_link",
                        entity_id=str(article_link_id),
                        severity="warning",
                        details={
                            "content_id": content_id,
                            "failure_reason": failure_reason,
                            **failure_details,
                        },
                    )
                    raise
                article_title = message.subject
                article_text = _email_body_fallback_text(message)
                content_id = self.gmail_repository.save_article_content(
                    article_link_id=article_link_id,
                    fetch_status="email_fallback" if article_text else "failed",
                    final_url=candidate.headline_link.url if article_text else None,
                    http_status=None,
                    title=article_title if article_text else None,
                    extracted_text=article_text,
                    failure_reason=failure_reason,
                )
                self.run_repository.add_event(
                    run_id=run_id,
                    event_type="article_content_fetch_failed",
                    stage="article_content",
                    message=(
                        "Article content fetch failed; falling back to email-body analysis"
                        if article_text
                        else "Article content fetch failed; falling back to headline-only analysis"
                    ),
                    entity_type="article_link",
                    entity_id=str(article_link_id),
                    severity="warning",
                    details={
                        "content_id": content_id,
                        "failure_reason": failure_reason,
                        "fallback_text_char_count": len(article_text or ""),
                        **failure_details,
                    },
                )
            else:
                content_id = self.gmail_repository.save_article_content(
                    article_link_id=article_link_id,
                    fetch_status="fetched",
                    final_url=content.final_url,
                    http_status=content.http_status,
                    title=content.title,
                    extracted_text=content.extracted_text,
                    failure_reason=None,
                )
                article_title = content.title
                article_text = content.extracted_text
                self.run_repository.add_event(
                    run_id=run_id,
                    event_type="article_content_extracted",
                    stage="article_content",
                    message="Article content extracted",
                    entity_type="article_link",
                    entity_id=str(article_link_id),
                    details={
                        "content_id": content_id,
                        "text_char_count": len(content.extracted_text),
                        "http_status": content.http_status,
                    },
                )

        if self.article_prechecker is not None:
            try:
                precheck = self.article_prechecker.precheck_article(
                    url=candidate.headline_link.url,
                    source_key=candidate.source.source_key,
                    email_subject=message.subject,
                    article_title=article_title,
                    article_text=article_text,
                    model=extraction_model,
                )
            except Exception as exc:
                self.run_repository.add_event(
                    run_id=run_id,
                    event_type="article_precheck_failed",
                    stage="article_precheck",
                    message="Article precheck failed; continuing with full article analysis",
                    entity_type="article_link",
                    entity_id=str(article_link_id),
                    severity="warning",
                    details={
                        "model": extraction_model,
                        "failure_reason": str(exc),
                    },
                )
            else:
                self.run_repository.add_event(
                    run_id=run_id,
                    event_type="article_prechecked",
                    stage="article_precheck",
                    message="Article relevance precheck completed",
                    entity_type="article_link",
                    entity_id=str(article_link_id),
                    details={
                        "provider": precheck.provider,
                        "model": precheck.model,
                        "is_relevant": precheck.is_relevant,
                        "confidence": precheck.confidence,
                        "tickers": precheck.tickers,
                        "reason": precheck.reason,
                    },
                )

        analysis = self.article_analyzer.analyze_article(
            url=candidate.headline_link.url,
            source_key=candidate.source.source_key,
            email_subject=message.subject,
            article_title=article_title,
            article_text=article_text,
            model=summary_model,
        )
        analysis_id = self.gmail_repository.save_article_analysis(
            article_link_id=article_link_id,
            provider=analysis.provider,
            model=analysis.model,
            summary=analysis.summary,
            stance=analysis.stance,
            confidence=analysis.confidence,
            supporting_evidence=analysis.supporting_evidence,
            mentioned_tickers=analysis.mentioned_tickers,
            raw_response=analysis.raw_response,
        )
        self.run_repository.add_event(
            run_id=run_id,
            event_type="article_analyzed",
            stage="article_analysis",
            message="Article analyzed",
            entity_type="article_link",
            entity_id=str(article_link_id),
            details={
                "analysis_id": analysis_id,
                "provider": analysis.provider,
                "model": analysis.model,
                "stance": analysis.stance,
                "confidence": analysis.confidence,
            },
        )
        return needs_source_login

    def _enrich_portfolio_tickers(
        self,
        run_id: int,
        already_attempted: set[str] | None = None,
        max_new_tickers: int | None = None,
        respect_stop: bool = True,
    ) -> int:
        if self.rating_enricher is None:
            return 0
        already_attempted = already_attempted if already_attempted is not None else set()
        active_watchlist_items = _active_watchlist_items(self.run_repository.database_path)
        active_watchlist_tickers = set(active_watchlist_items)
        attempted_count = 0
        for ticker in _portfolio_tickers(
            self.run_repository.list_discovered_articles(run_id),
            active_watchlist_tickers=active_watchlist_tickers,
        ):
            if max_new_tickers is not None and attempted_count >= max_new_tickers:
                break
            if respect_stop and self.stop_requested():
                break
            if ticker in already_attempted:
                continue
            asset_type = active_watchlist_items.get(ticker, {}).get("asset_type")
            required_data_types = required_enrichment_data_types(
                asset_type=asset_type,
                include_polygon=getattr(self.rating_enricher, "polygon_client", None) is not None,
                include_research=getattr(self.rating_enricher, "include_research", False),
                include_investing=getattr(self.rating_enricher, "include_research", False),
            )
            if self.run_repository.has_complete_ticker_enrichments(
                run_id,
                ticker,
                required_data_types=required_data_types,
            ):
                already_attempted.add(ticker)
                self.run_repository.add_event(
                    run_id=run_id,
                    event_type="ticker_rating_enrichment_reused",
                    stage="ticker_enrichment",
                    message="Ticker rating enrichment reused from earlier in this run",
                    entity_type="ticker",
                    entity_id=ticker,
                )
                continue
            already_attempted.add(ticker)
            attempted_count += 1
            try:
                result = _call_enrich_ticker(
                    self.rating_enricher,
                    run_id=run_id,
                    ticker=ticker,
                    asset_type=asset_type,
                    company_name=active_watchlist_items.get(ticker, {}).get("company_name"),
                )
            except Exception as exc:
                self.run_repository.add_event(
                    run_id=run_id,
                    event_type="ticker_rating_enrichment_failed",
                    stage="ticker_enrichment",
                    message="Ticker rating enrichment failed; continuing run",
                    entity_type="ticker",
                    entity_id=ticker,
                    severity="warning",
                    details={"failure_reason": str(exc)},
                )
                continue
            self.run_repository.add_event(
                run_id=run_id,
                event_type="ticker_rating_enriched",
                stage="ticker_enrichment",
                message="Ticker rating enrichment completed",
                entity_type="ticker",
                entity_id=ticker,
                details=result,
            )
        return attempted_count

    def _try_enrich_portfolio_tickers(
        self,
        run_id: int,
        already_attempted: set[str] | None = None,
        max_new_tickers: int | None = None,
        respect_stop: bool = True,
    ) -> int:
        try:
            return self._enrich_portfolio_tickers(
                run_id,
                already_attempted=already_attempted,
                max_new_tickers=max_new_tickers,
                respect_stop=respect_stop,
            )
        except Exception as exc:
            self.run_repository.add_event(
                run_id=run_id,
                event_type="ticker_rating_enrichment_failed",
                stage="ticker_enrichment",
                message="Ticker rating enrichment failed; continuing run",
                severity="warning",
                details={"failure_reason": str(exc)},
            )
            return 0

    def _try_synthesize_run_report(self, run_id: int, model: str | None = None) -> None:
        if self.report_synthesizer is None:
            return
        try:
            result = self.report_synthesizer.synthesize_run(
                run=self.run_repository.get_run(run_id),
                articles=self.run_repository.list_discovered_articles(run_id),
                ticker_enrichments=self.run_repository.list_ticker_enrichments(run_id),
                model=model,
            )
        except Exception as exc:
            self.run_repository.add_event(
                run_id=run_id,
                event_type="run_report_synthesis_failed",
                stage="report_synthesis",
                message="Run-level report synthesis failed; deterministic report export remains available",
                severity="warning",
                details={"model": model, "failure_reason": str(exc)},
            )
            return
        self.run_repository.add_event(
            run_id=run_id,
            event_type="run_report_synthesized",
            stage="report_synthesis",
            message="Run-level report synthesis completed",
            details={
                "provider": result.provider,
                "model": result.model,
                "executive_summary": result.executive_summary,
                "priority_tickers": result.priority_tickers,
                "contradictions": result.contradictions,
                "recommended_actions": result.recommended_actions,
            },
        )


def _format_gmail_internal_date(internal_date_ms: int) -> str | None:
    if not internal_date_ms:
        return None
    return datetime.fromtimestamp(internal_date_ms / 1000, tz=timezone.utc).isoformat()


def _is_openai_quota_error(exc: Exception) -> bool:
    message = str(exc).lower()
    quota_markers = [
        "insufficient_quota",
        "you exceeded your current quota",
        "check your plan and billing",
    ]
    return any(marker in message for marker in quota_markers)


def _email_body_fallback_text(message) -> str | None:
    if message.html_body:
        text = extract_readable_text_from_html(message.html_body)
    else:
        text = message.text_body.strip()
    if not text:
        return None
    return text[:12000]


def _portfolio_tickers(
    articles: list[dict],
    active_watchlist_tickers: set[str] | None = None,
) -> list[str]:
    active_watchlist_tickers = active_watchlist_tickers or set()
    tickers: set[str] = set()
    for article in articles:
        analysis = article.get("analysis") or {}
        specific_tickers: set[str] = set()
        for collection_name in ("actionable_data", "actionable_signals", "price_targets", "rating_snapshots"):
            for item in analysis.get(collection_name) or []:
                ticker = normalize_ticker(str(item.get("ticker") or ""))
                if ticker and ticker in active_watchlist_tickers:
                    specific_tickers.add(ticker)
        if specific_tickers:
            tickers.update(specific_tickers)
            continue
        for detail in analysis.get("mentioned_ticker_details") or []:
            ticker = normalize_ticker(str(detail.get("ticker") or ""))
            if ticker and detail.get("in_portfolio") and ticker in active_watchlist_tickers:
                tickers.add(ticker)
    return sorted(tickers)


def _active_watchlist_tickers(database_path: str) -> set[str]:
    return set(_active_watchlist_items(database_path))


def _active_watchlist_items(database_path: str) -> dict[str, dict]:
    items = {}
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


def _json_object(value) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _asset_type_from_polygon_reference(reference: dict) -> str | None:
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
