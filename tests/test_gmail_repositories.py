from email_article_analyzer.db import initialize_database
from email_article_analyzer.repositories import (
    GmailDiscoveryRepository,
    RunRepository,
    WatchlistRepository,
)


def test_gmail_repository_saves_message_and_article_link(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    repo = GmailDiscoveryRepository(db_path)

    gmail_row_id = repo.save_message(
        run_id=None,
        gmail_message_id="msg-1",
        thread_id="thread-1",
        sender="alerts@seekingalpha.com",
        subject="Story",
        labels=["UNREAD"],
        source_key="seeking_alpha",
        processing_status="discovered",
    )
    link_id = repo.save_article_link(
        gmail_message_row_id=gmail_row_id,
        source_key="seeking_alpha",
        raw_url="https://seekingalpha.com/article/1",
        normalized_url="https://seekingalpha.com/article/1",
        detection_method="headline_anchor",
        detection_confidence=0.9,
        heuristic_notes="h1 anchor",
    )

    message = repo.get_message(gmail_row_id)
    link = repo.get_article_link(link_id)

    assert message["gmail_message_id"] == "msg-1"
    assert message["labels_json"] == '["UNREAD"]'
    assert link["detection_method"] == "headline_anchor"


def test_gmail_repository_saves_article_analysis(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    repo = GmailDiscoveryRepository(db_path)
    gmail_row_id = repo.save_message(
        run_id=None,
        gmail_message_id="msg-1",
        thread_id="thread-1",
        sender="alerts@seekingalpha.com",
        subject="Story",
        labels=["UNREAD"],
        source_key="seeking_alpha",
        processing_status="discovered",
    )
    link_id = repo.save_article_link(
        gmail_message_row_id=gmail_row_id,
        source_key="seeking_alpha",
        raw_url="https://seekingalpha.com/article/1",
        normalized_url="https://seekingalpha.com/article/1",
        detection_method="headline_anchor",
        detection_confidence=0.9,
        heuristic_notes="h1 anchor",
    )

    analysis_id = repo.save_article_analysis(
        article_link_id=link_id,
        provider="openai",
        model="gpt-summary",
        summary="Margins improved after a stronger guide.",
        stance="buy_watch",
        confidence=0.82,
        supporting_evidence=["Raised FY guide", "Gross margin expanded"],
        mentioned_tickers=["NVDA"],
        raw_response={"id": "resp-1"},
    )

    analysis = repo.get_article_analysis(analysis_id)

    assert analysis["article_link_id"] == link_id
    assert analysis["provider"] == "openai"
    assert analysis["model"] == "gpt-summary"
    assert analysis["stance"] == "buy_watch"
    assert analysis["confidence"] == 0.82
    assert analysis["supporting_evidence_json"] == '["Raised FY guide", "Gross margin expanded"]'
    assert analysis["mentioned_tickers_json"] == '["NVDA"]'


def test_gmail_repository_saves_article_content(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    repo = GmailDiscoveryRepository(db_path)
    gmail_row_id = repo.save_message(
        run_id=None,
        gmail_message_id="msg-1",
        thread_id="thread-1",
        sender="alerts@seekingalpha.com",
        subject="Story",
        labels=["UNREAD"],
        source_key="seeking_alpha",
        processing_status="discovered",
    )
    link_id = repo.save_article_link(
        gmail_message_row_id=gmail_row_id,
        source_key="seeking_alpha",
        raw_url="https://seekingalpha.com/article/1",
        normalized_url="https://seekingalpha.com/article/1",
        detection_method="headline_anchor",
        detection_confidence=0.9,
        heuristic_notes="h1 anchor",
    )

    content_id = repo.save_article_content(
        article_link_id=link_id,
        fetch_status="fetched",
        final_url="https://seekingalpha.com/article/1",
        http_status=200,
        title="Story",
        extracted_text="A long article body.",
        failure_reason=None,
    )

    content = repo.get_article_content(content_id)

    assert content["article_link_id"] == link_id
    assert content["fetch_status"] == "fetched"
    assert content["http_status"] == 200
    assert content["title"] == "Story"
    assert content["text_char_count"] == len("A long article body.")


def test_list_discovered_articles_marks_mentioned_tickers_in_active_watchlist(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    watchlist_repo = WatchlistRepository(db_path)
    upload_id = watchlist_repo.create_upload(
        original_filename="portfolio.csv",
        columns=["Ticker"],
        sample_rows=[{"Ticker": "AAPL"}],
        row_count=1,
    )
    watchlist_repo.replace_items(
        upload_id,
        [
            {
                "ticker": "AAPL",
                "normalized_ticker": "AAPL",
                "company_name": "Apple",
                "sector": None,
                "priority": None,
                "notes": None,
                "polygon_reference": "{}",
            }
        ],
    )
    gmail_repo = GmailDiscoveryRepository(db_path)
    run_id = RunRepository(db_path).create_run("gpt-extract", "gpt-summary")
    gmail_row_id = gmail_repo.save_message(
        run_id=run_id,
        gmail_message_id="msg-1",
        thread_id="thread-1",
        sender="alerts@seekingalpha.com",
        subject="Story",
        labels=["UNREAD"],
        source_key="seeking_alpha",
        processing_status="discovered",
    )
    link_id = gmail_repo.save_article_link(
        gmail_message_row_id=gmail_row_id,
        source_key="seeking_alpha",
        raw_url="https://seekingalpha.com/article/1",
        normalized_url="https://seekingalpha.com/article/1",
        detection_method="headline_anchor",
        detection_confidence=0.9,
        heuristic_notes=None,
    )
    gmail_repo.save_article_analysis(
        article_link_id=link_id,
        provider="openai",
        model="gpt-summary",
        summary="Apple and Microsoft update.",
        stance="hold",
        confidence=0.75,
        supporting_evidence=["Evidence"],
        mentioned_tickers=["AAPL", "MSFT"],
        raw_response={},
    )

    articles = RunRepository(db_path).list_discovered_articles(run_id=run_id)

    assert articles[0]["analysis"]["mentioned_ticker_details"] == [
        {"ticker": "AAPL", "in_portfolio": True},
        {"ticker": "MSFT", "in_portfolio": False},
    ]
