from dataclasses import dataclass

from email_article_analyzer.article_analysis import ArticleAnalyzer
from email_article_analyzer.article_content import (
    ArticleContentFetcherProtocol,
    extract_readable_text_from_html,
)
from email_article_analyzer.gmail import GmailCandidate
from email_article_analyzer.model_defaults import DEFAULT_EXTRACTION_MODEL
from email_article_analyzer.model_defaults import DEFAULT_SUMMARY_MODEL
from email_article_analyzer.model_defaults import normalize_model_name
from email_article_analyzer.repositories import GmailDiscoveryRepository, RunRepository


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
        article_content_fetcher: ArticleContentFetcherProtocol | None = None,
        stop_requested=None,
    ):
        self.run_repository = run_repository
        self.gmail_repository = gmail_repository
        self.discovery_service = discovery_service
        self.article_analyzer = article_analyzer
        self.article_content_fetcher = article_content_fetcher
        self.stop_requested = stop_requested or (lambda: False)

    def start_discovery_run(
        self,
        extraction_model: str | None,
        summary_model: str | None,
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
        self.run_repository.add_event(
            run_id=run_id,
            event_type="run_started",
            stage="startup",
            message="Run started",
            details={
                "extraction_model": extraction_model,
                "summary_model": summary_model,
            },
        )
        self.run_repository.add_event(
            run_id=run_id,
            event_type="gmail_search_started",
            stage="gmail_discovery",
            message="Gmail discovery started",
        )

        candidates = self.discovery_service.discover_candidates()
        processed_count = 0
        stopped = False
        needed_source_logins: set[str] = set()
        for candidate in candidates:
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
                        "candidate_count": len(candidates),
                    },
                )
                break
            if self.run_repository.has_analyzed_gmail_message(candidate.message.message_id):
                self.discovery_service.mark_success(candidate.message.message_id)
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
                if self._persist_candidate(run_id, candidate, summary_model):
                    needed_source_logins.add(candidate.source.source_key)
                self.discovery_service.mark_success(candidate.message.message_id)
                processed_count += 1
            except Exception as exc:
                self.discovery_service.mark_failure(candidate.message.message_id)
                self.run_repository.add_event(
                    run_id=run_id,
                    event_type="candidate_processing_failed",
                    stage="article_analysis",
                    message="Candidate processing failed; continuing run",
                    entity_type="gmail_message",
                    entity_id=candidate.message.message_id,
                    severity="warning",
                    details={
                        "source_key": candidate.source.source_key,
                        "url": candidate.headline_link.url,
                        "failure_reason": str(exc),
                    },
                )
                processed_count += 1

        final_status = "stopped" if stopped else "completed"
        self.run_repository.complete_run(run_id, status=final_status)
        self.run_repository.add_event(
            run_id=run_id,
            event_type="run_stopped" if stopped else "run_completed",
            stage="completion",
            message="Run stopped" if stopped else "Run completed",
            details={
                "candidate_count": len(candidates),
                "processed_count": processed_count,
            },
        )
        return RunResult(
            run_id=run_id,
            status=final_status,
            candidate_count=processed_count,
            needed_source_logins=sorted(needed_source_logins),
        )

    def _persist_candidate(
        self,
        run_id: int,
        candidate: GmailCandidate,
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


def _email_body_fallback_text(message) -> str | None:
    if message.html_body:
        text = extract_readable_text_from_html(message.html_body)
    else:
        text = message.text_body.strip()
    if not text:
        return None
    return text[:12000]
