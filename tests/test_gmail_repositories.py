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
