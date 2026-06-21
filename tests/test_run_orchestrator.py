from email_article_analyzer.db import initialize_database
from email_article_analyzer.article_analysis import ArticleAnalysisResult
from email_article_analyzer.gmail import GmailCandidate, GmailMessage
from email_article_analyzer.link_extraction import ExtractedLink
from email_article_analyzer.model_defaults import DEFAULT_EXTRACTION_MODEL
from email_article_analyzer.model_defaults import DEFAULT_SUMMARY_MODEL
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


class FakeArticleAnalyzer:
    def __init__(self):
        self.calls = []

    def analyze_article(
        self,
        url,
        source_key,
        email_subject,
        article_title,
        article_text,
        model,
    ):
        self.calls.append(
            {
                "url": url,
                "source_key": source_key,
                "email_subject": email_subject,
                "article_title": article_title,
                "article_text": article_text,
                "model": model,
            }
        )
        return ArticleAnalysisResult(
            provider="openai",
            model=model,
            summary="Margins improved after a stronger guide.",
            stance="buy_watch",
            confidence=0.82,
            supporting_evidence=["Raised FY guide", "Gross margin expanded"],
            mentioned_tickers=["NVDA"],
            raw_response={"id": "resp-1"},
        )


class FakeArticleContent:
    final_url = "https://seekingalpha.com/article/1"
    http_status = 200
    title = "Story title"
    extracted_text = "Nvidia raised guidance. Gross margin expanded."


class FakeArticleContentFetcher:
    def __init__(self):
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        return FakeArticleContent()


class FailingArticleContentFetcher:
    def __init__(self):
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        raise RuntimeError("HTTP 403 Forbidden")


class FailingArticleAnalyzer:
    def analyze_article(
        self,
        url,
        source_key,
        email_subject,
        article_title,
        article_text,
        model,
    ):
        raise RuntimeError("OpenAI request failed")


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


def test_run_orchestrator_analyzes_discovered_headline_link_when_analyzer_is_configured(tmp_path):
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
    analyzer = FakeArticleAnalyzer()
    content_fetcher = FakeArticleContentFetcher()
    run_repo = RunRepository(db_path)
    gmail_repo = GmailDiscoveryRepository(db_path)
    orchestrator = RunOrchestrator(
        run_repository=run_repo,
        gmail_repository=gmail_repo,
        discovery_service=discovery_service,
        article_analyzer=analyzer,
        article_content_fetcher=content_fetcher,
    )

    result = orchestrator.start_discovery_run(
        extraction_model="gpt-extract",
        summary_model="gpt-summary",
    )

    assert content_fetcher.calls == ["https://seekingalpha.com/article/1"]
    assert analyzer.calls == [
        {
            "url": "https://seekingalpha.com/article/1",
            "source_key": "seeking_alpha",
            "email_subject": "Story",
            "article_title": "Story title",
            "article_text": "Nvidia raised guidance. Gross margin expanded.",
            "model": "gpt-summary",
        }
    ]
    events = run_repo.list_events(result.run_id)
    assert [event["event_type"] for event in events] == [
        "run_started",
        "gmail_search_started",
        "headline_link_detected",
        "article_content_extracted",
        "article_analyzed",
        "run_completed",
    ]
    content = gmail_repo.get_article_content(1)
    assert content["title"] == "Story title"
    assert content["text_char_count"] == len("Nvidia raised guidance. Gross margin expanded.")
    analysis = gmail_repo.get_article_analysis(1)
    assert analysis["summary"] == "Margins improved after a stronger guide."
    assert analysis["stance"] == "buy_watch"


def test_run_orchestrator_uses_default_models_when_inputs_are_blank(tmp_path):
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
    analyzer = FakeArticleAnalyzer()
    run_repo = RunRepository(db_path)
    gmail_repo = GmailDiscoveryRepository(db_path)
    orchestrator = RunOrchestrator(
        run_repository=run_repo,
        gmail_repository=gmail_repo,
        discovery_service=FakeDiscoveryService([candidate]),
        article_analyzer=analyzer,
    )

    result = orchestrator.start_discovery_run(
        extraction_model="",
        summary_model=None,
    )

    run = run_repo.get_run(result.run_id)
    assert run["extraction_model"] == DEFAULT_EXTRACTION_MODEL
    assert run["summary_model"] == DEFAULT_SUMMARY_MODEL
    assert analyzer.calls[0]["model"] == DEFAULT_SUMMARY_MODEL


def test_run_orchestrator_records_failed_content_fetch_and_falls_back_to_headline_analysis(tmp_path):
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
            html_body=(
                "<html><body><nav>unsubscribe</nav><h1>Story</h1>"
                "<p>Nvidia raised guidance in the newsletter excerpt.</p>"
                "<p>Gross margin expanded to 75%.</p></body></html>"
            ),
            text_body="Plain text fallback should not be used when HTML is available.",
        ),
        source=source,
        headline_link=ExtractedLink(
            url="https://seekingalpha.com/article/1",
            detection_method="headline_anchor",
            detection_confidence=0.9,
        ),
    )
    analyzer = FakeArticleAnalyzer()
    content_fetcher = FailingArticleContentFetcher()
    run_repo = RunRepository(db_path)
    gmail_repo = GmailDiscoveryRepository(db_path)
    orchestrator = RunOrchestrator(
        run_repository=run_repo,
        gmail_repository=gmail_repo,
        discovery_service=FakeDiscoveryService([candidate]),
        article_analyzer=analyzer,
        article_content_fetcher=content_fetcher,
    )

    result = orchestrator.start_discovery_run(
        extraction_model="gpt-extract",
        summary_model="gpt-summary",
    )

    assert result.status == "completed"
    assert analyzer.calls == [
        {
            "url": "https://seekingalpha.com/article/1",
            "source_key": "seeking_alpha",
            "email_subject": "Story",
            "article_title": "Story",
            "article_text": (
                "Story\n"
                "Nvidia raised guidance in the newsletter excerpt.\n"
                "Gross margin expanded to 75%."
            ),
            "model": "gpt-summary",
        }
    ]
    content = gmail_repo.get_article_content(1)
    assert content["fetch_status"] == "email_fallback"
    assert content["title"] == "Story"
    assert content["text_char_count"] == len(
        "Story\n"
        "Nvidia raised guidance in the newsletter excerpt.\n"
        "Gross margin expanded to 75%."
    )
    assert content["failure_reason"] == "HTTP 403 Forbidden"
    events = run_repo.list_events(result.run_id)
    assert [event["event_type"] for event in events] == [
        "run_started",
        "gmail_search_started",
        "headline_link_detected",
        "article_content_fetch_failed",
        "article_analyzed",
        "run_completed",
    ]
    warning = events[3]
    assert warning["severity"] == "warning"
    assert warning["message"] == "Article content fetch failed; falling back to email-body analysis"


def test_run_orchestrator_records_candidate_failure_and_completes_run(tmp_path):
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
    run_repo = RunRepository(db_path)
    orchestrator = RunOrchestrator(
        run_repository=run_repo,
        gmail_repository=GmailDiscoveryRepository(db_path),
        discovery_service=FakeDiscoveryService([candidate]),
        article_analyzer=FailingArticleAnalyzer(),
    )

    result = orchestrator.start_discovery_run(
        extraction_model="gpt-extract",
        summary_model="gpt-summary",
    )

    run = run_repo.get_run(result.run_id)
    assert result.status == "completed"
    assert run["status"] == "completed"
    events = run_repo.list_events(result.run_id)
    assert [event["event_type"] for event in events] == [
        "run_started",
        "gmail_search_started",
        "headline_link_detected",
        "candidate_processing_failed",
        "run_completed",
    ]
    assert events[3]["severity"] == "warning"
    assert events[3]["message"] == "Candidate processing failed; continuing run"
