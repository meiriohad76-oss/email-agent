from email_article_analyzer.link_extraction import extract_headline_link
from email_article_analyzer.sources import TRUSTED_SOURCES


SEEKING_ALPHA = next(source for source in TRUSTED_SOURCES if source.source_key == "seeking_alpha")


def test_extract_headline_link_prefers_large_headline_anchor():
    html = """
    <html>
      <body>
        <a href="https://seekingalpha.com/account">Account</a>
        <h1><a href="https://seekingalpha.com/article/123-main-story">Main Story</a></h1>
        <a href="https://seekingalpha.com/article/456-related">Related</a>
      </body>
    </html>
    """

    result = extract_headline_link(html=html, text="", source=SEEKING_ALPHA)

    assert result.url == "https://seekingalpha.com/article/123-main-story"
    assert result.detection_method == "headline_anchor"


def test_extract_headline_link_falls_back_to_first_article_domain_link():
    html = """
    <a href="https://example.com/not-source">Ad</a>
    <a href="https://seekingalpha.com/article/789-first-valid">First Valid</a>
    """

    result = extract_headline_link(html=html, text="", source=SEEKING_ALPHA)

    assert result.url == "https://seekingalpha.com/article/789-first-valid"
    assert result.detection_method == "first_valid_link"


def test_extract_headline_link_can_read_plain_text_urls():
    text = "Read now: https://seekingalpha.com/article/999-text-story"

    result = extract_headline_link(html="", text=text, source=SEEKING_ALPHA)

    assert result.url == "https://seekingalpha.com/article/999-text-story"
    assert result.detection_method == "first_text_url"


def test_extract_headline_link_returns_none_when_no_source_link_exists():
    assert extract_headline_link(
        html="<a href='https://example.com'>x</a>",
        text="",
        source=SEEKING_ALPHA,
    ) is None
