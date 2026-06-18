from email_article_analyzer.db import initialize_database
from email_article_analyzer.repositories import GmailDiscoveryRepository


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
