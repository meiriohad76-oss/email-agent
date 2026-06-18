from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Protocol

import httpx


@dataclass(frozen=True)
class ArticleContent:
    final_url: str
    http_status: int
    title: str | None
    extracted_text: str


class ArticleContentFetcherProtocol(Protocol):
    def fetch(self, url: str) -> ArticleContent:
        pass


class _ReadableTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.body_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        text = " ".join(data.split())
        if not text or self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(text)
        else:
            self.body_parts.append(text)

    @property
    def title(self) -> str | None:
        value = " ".join(self.title_parts).strip()
        return value or None

    @property
    def body(self) -> str:
        return "\n".join(part for part in self.body_parts if part).strip()


class ArticleContentFetcher:
    def __init__(self, http_client=None, timeout_seconds: float = 20.0):
        self.http_client = http_client or httpx.Client()
        self.timeout_seconds = timeout_seconds

    def fetch(self, url: str) -> ArticleContent:
        response = self.http_client.get(
            url,
            follow_redirects=True,
            timeout=self.timeout_seconds,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 email-article-analyzer/0.1 "
                    "(stock article research automation)"
                )
            },
        )
        response.raise_for_status()
        parser = _ReadableTextParser()
        parser.feed(response.text)
        return ArticleContent(
            final_url=str(response.url),
            http_status=int(response.status_code),
            title=parser.title,
            extracted_text=parser.body,
        )
