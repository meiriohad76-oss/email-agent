from dataclasses import dataclass
from html.parser import HTMLParser
import base64
import re
from urllib.parse import parse_qs, unquote, urlparse

from email_article_analyzer.sources import TrustedSource, match_source_for_url


@dataclass(frozen=True)
class ExtractedLink:
    url: str
    detection_method: str
    detection_confidence: float


_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
_HEADING_TAGS = {"h1", "h2"}
_HEADLINE_FONT_PX = 20
_FONT_SIZE_PATTERN = re.compile(r"font-size:\s*(\d+(?:\.\d+)?)px", re.IGNORECASE)


class _AnchorParser(HTMLParser):
    """Collects link hrefs and whether each sits in a headline.

    A headline is an anchor inside an h1/h2, or inside an element styled with a
    large font size. Seeking Alpha emails use styled spans instead of headings.
    """

    def __init__(self):
        super().__init__()
        self.anchors: list[tuple[str, bool]] = []
        self._open: list[tuple[str, bool]] = []

    @property
    def in_heading(self) -> bool:
        return any(is_headline for _, is_headline in self._open)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attributes = dict(attrs)
        if tag == "a":
            href = attributes.get("href")
            if href:
                self.anchors.append((href, self.in_heading))
        if tag in _VOID_TAGS:
            return
        is_headline = tag in _HEADING_TAGS or _is_headline_style(attributes.get("style"))
        self._open.append((tag, is_headline))

    def handle_endtag(self, tag):
        tag = tag.lower()
        for index in range(len(self._open) - 1, -1, -1):
            if self._open[index][0] == tag:
                del self._open[index:]
                return


def _is_headline_style(style: str | None) -> bool:
    if not style:
        return False
    sizes = [float(size) for size in _FONT_SIZE_PATTERN.findall(style)]
    return any(size >= _HEADLINE_FONT_PX for size in sizes)


def extract_headline_link(html: str, text: str, source: TrustedSource) -> ExtractedLink | None:
    parser = _AnchorParser()
    parser.feed(html or "")

    source_links = []
    for href, in_heading in parser.anchors:
        article_url = _source_article_url(href, source)
        if article_url:
            source_links.append((article_url, in_heading))
    for href, in_heading in source_links:
        if in_heading:
            return ExtractedLink(href, "headline_anchor", 0.9)
    if source_links:
        return ExtractedLink(source_links[0][0], "first_valid_link", 0.65)

    for url in re.findall(r"https?://\S+", text or ""):
        cleaned = url.rstrip(").,;]")
        article_url = _source_article_url(cleaned, source)
        if article_url:
            return ExtractedLink(article_url, "first_text_url", 0.55)
    return None


def _source_article_url(url: str, source: TrustedSource) -> str | None:
    candidates = [url, *_unwrap_tracking_urls(url)]
    for candidate in candidates:
        if _belongs_to_source(candidate, source) and _is_analyzable_source_link(candidate, source):
            return candidate
    return None


def _belongs_to_source(url: str, source: TrustedSource) -> bool:
    matched = match_source_for_url(url)
    return matched is not None and matched.source_key == source.source_key


def _is_analyzable_source_link(url: str, source: TrustedSource) -> bool:
    if source.source_key == "seeking_alpha":
        return _looks_like_seeking_alpha_article_link(url)
    if source.source_key == "zacks":
        return _looks_like_zacks_article_link(url)
    return True


def _looks_like_seeking_alpha_article_link(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.startswith("/article/") or path.startswith("/news/")


def _looks_like_zacks_article_link(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    expanded = _expanded_url_text(url)
    if "/stock/news/" in path or "/commentary/" in path:
        return True
    return "zacks.com/stock/news/" in expanded or "zacks.com/commentary/" in expanded


def _expanded_url_text(url: str) -> str:
    expanded = url.lower()
    for _ in range(3):
        decoded = unquote(expanded)
        if decoded == expanded:
            break
        expanded = decoded
    return expanded


def _unwrap_tracking_urls(url: str) -> list[str]:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host.endswith("seekingalpha.com") and parsed.path.startswith("/click/"):
        return _decode_seeking_alpha_tracking_urls(parsed.path)
    return []


def _decode_seeking_alpha_tracking_urls(path: str) -> list[str]:
    urls: list[str] = []
    for segment in path.split("/"):
        if not segment:
            continue
        decoded = _decode_base64_url_segment(segment)
        if not decoded:
            continue
        urls.append(decoded)
        urls.extend(_extract_nested_ref_urls(decoded))
    return urls


def _decode_base64_url_segment(segment: str) -> str | None:
    padding = "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode((segment + padding).encode("ascii")).decode(
            "utf-8",
            errors="replace",
        )
    except (ValueError, UnicodeDecodeError):
        return None


def _extract_nested_ref_urls(url: str) -> list[str]:
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("ref", [])
    return [unquote(value) for value in values if value]
