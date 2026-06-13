from dataclasses import dataclass
from html.parser import HTMLParser
import re

from email_article_analyzer.sources import TrustedSource, match_source_for_url


@dataclass(frozen=True)
class ExtractedLink:
    url: str
    detection_method: str
    detection_confidence: float


class _AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_heading = False
        self.anchors: list[tuple[str, bool]] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"h1", "h2"}:
            self.in_heading = True
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href:
                self.anchors.append((href, self.in_heading))

    def handle_endtag(self, tag):
        if tag.lower() in {"h1", "h2"}:
            self.in_heading = False


def extract_headline_link(html: str, text: str, source: TrustedSource) -> ExtractedLink | None:
    parser = _AnchorParser()
    parser.feed(html or "")

    source_links = [
        (href, in_heading)
        for href, in_heading in parser.anchors
        if _belongs_to_source(href, source)
    ]
    for href, in_heading in source_links:
        if in_heading:
            return ExtractedLink(href, "headline_anchor", 0.9)
    if source_links:
        return ExtractedLink(source_links[0][0], "first_valid_link", 0.65)

    for url in re.findall(r"https?://\S+", text or ""):
        cleaned = url.rstrip(").,;]")
        if _belongs_to_source(cleaned, source):
            return ExtractedLink(cleaned, "first_text_url", 0.55)
    return None


def _belongs_to_source(url: str, source: TrustedSource) -> bool:
    matched = match_source_for_url(url)
    return matched is not None and matched.source_key == source.source_key
