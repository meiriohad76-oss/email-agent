from email_article_analyzer.sources import (
    TRUSTED_SOURCES,
    match_source_for_sender,
    match_source_for_url,
)


def test_trusted_sources_include_initial_mvp_sources():
    keys = {source.source_key for source in TRUSTED_SOURCES}

    assert {"seeking_alpha", "zacks", "investing"} <= keys


def test_match_source_for_sender_handles_common_newsletter_senders():
    assert match_source_for_sender("alerts@seekingalpha.com").source_key == "seeking_alpha"
    assert match_source_for_sender("newsletter@zacks.com").source_key == "zacks"
    assert match_source_for_sender("updates@investing.com").source_key == "investing"


def test_match_source_for_url_uses_article_domains():
    assert match_source_for_url("https://seekingalpha.com/article/123-test").source_key == "seeking_alpha"
    assert match_source_for_url("https://www.zacks.com/stock/news/123-test").source_key == "zacks"
    assert match_source_for_url("https://www.investing.com/news/stock-market-news/test").source_key == "investing"


def test_unknown_sender_or_url_returns_none():
    assert match_source_for_sender("person@example.com") is None
    assert match_source_for_url("https://example.com/article") is None
