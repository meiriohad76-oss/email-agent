from email_article_analyzer.gmail import build_unread_trusted_query
from email_article_analyzer.sources import TRUSTED_SOURCES


def test_build_unread_trusted_query_targets_unread_and_excludes_analyzed():
    query = build_unread_trusted_query(TRUSTED_SOURCES)

    assert "is:unread" in query
    assert "-label:Analyzed" in query
    assert "from:seekingalpha.com" in query
    assert "from:zacks.com" in query
    assert "from:investing.com" in query
