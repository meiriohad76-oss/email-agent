import base64

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


def test_extract_headline_link_skips_seeking_alpha_portfolio_pages():
    html = """
    <h1><a href="https://seekingalpha.com/account/portfolio/all/holdings">Portfolio</a></h1>
    <a href="https://seekingalpha.com/article/789-first-valid">First Valid</a>
    """

    result = extract_headline_link(html=html, text="", source=SEEKING_ALPHA)

    assert result.url == "https://seekingalpha.com/article/789-first-valid"
    assert result.detection_method == "first_valid_link"


def test_extract_headline_link_returns_none_for_seeking_alpha_non_article_pages():
    html = """
    <h1><a href="https://seekingalpha.com/account/portfolio/all/holdings">Portfolio</a></h1>
    <a href="https://seekingalpha.com/">Home</a>
    """

    assert extract_headline_link(html=html, text="", source=SEEKING_ALPHA) is None


def test_extract_headline_link_can_read_plain_text_urls():
    text = "Read now: https://seekingalpha.com/article/999-text-story"

    result = extract_headline_link(html="", text=text, source=SEEKING_ALPHA)

    assert result.url == "https://seekingalpha.com/article/999-text-story"
    assert result.detection_method == "first_text_url"


def test_extract_headline_link_unwraps_seeking_alpha_email_tracking_links():
    article_url = (
        "https://seekingalpha.com/account/email-auth?"
        "ref=https%3A%2F%2Fseekingalpha.com%2Farticle%2F4916050-main-story"
        "%3Fposition%3Dmust_reads"
    )
    encoded = base64.urlsafe_b64encode(article_url.encode("utf-8")).decode("ascii").rstrip("=")
    tracking_url = f"https://email-st.seekingalpha.com/click/46245308.103702/{encoded}"
    html = f"<h1><a href='{tracking_url}'>Main Story</a></h1>"

    result = extract_headline_link(html=html, text="", source=SEEKING_ALPHA)

    assert result.url == "https://seekingalpha.com/article/4916050-main-story?position=must_reads"
    assert result.detection_method == "headline_anchor"


def test_extract_headline_link_returns_none_when_no_source_link_exists():
    assert extract_headline_link(
        html="<a href='https://example.com'>x</a>",
        text="",
        source=SEEKING_ALPHA,
    ) is None
