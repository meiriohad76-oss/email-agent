from email_article_analyzer.db import initialize_database
from email_article_analyzer.gmail import GmailCandidate, GmailMessage
from email_article_analyzer.link_extraction import ExtractedLink
from email_article_analyzer.repositories import GmailDiscoveryRepository, RunRepository
from email_article_analyzer.run_orchestration import RunOrchestrator
from email_article_analyzer.sources import TRUSTED_SOURCES


class FakeDiscoveryService:
    def __init__(self, candidates):
        self.candidates = candidates
        self.called = False

    def discover_candidates(self):
        self.called = True
        return self.candidates


def test_run_orchestrator_persists_candidates_events_and_needed_logins(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    source = next(source for source in TRUSTED_SOURCES if source.source_key == "seeking_alpha")
    candidate = GmailCandidate(
        message=GmailMessage(
            message_id="msg-1",
            thread_id="thread-1",
            sender="alerts@seekingalpha.com",
            subject="Story",
            labels=["UNREAD"],
            html_body="<h1>Story</h1>",
            text_body="",
        ),
        source=source,
        headline_link=ExtractedLink(
            url="https://seekingalpha.com/article/1",
            detection_method="headline_anchor",
            detection_confidence=0.9,
        ),
    )
    discovery_service = FakeDiscoveryService([candidate])
    run_repo = RunRepository(db_path)
    gmail_repo = GmailDiscoveryRepository(db_path)
    orchestrator = RunOrchestrator(
        run_repository=run_repo,
        gmail_repository=gmail_repo,
        discovery_service=discovery_service,
    )

    result = orchestrator.start_discovery_run(
        extraction_model="gpt-extract",
        summary_model="gpt-summary",
    )

    assert discovery_service.called is True
    assert result.status == "completed"
    assert result.candidate_count == 1
    assert result.needed_source_logins == ["seeking_alpha"]
    assert run_repo.discovery_counts(result.run_id) == {
        "gmail_messages": 1,
        "article_links": 1,
    }
    event_types = [event["event_type"] for event in run_repo.list_events(result.run_id)]
    assert event_types == [
        "run_started",
        "gmail_search_started",
        "headline_link_detected",
        "run_completed",
    ]
