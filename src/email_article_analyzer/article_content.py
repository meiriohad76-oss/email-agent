from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
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


def extract_readable_text_from_html(html: str) -> str:
    parser = _ReadableTextParser()
    parser.feed(html)
    return parser.body


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


class BrowserArticleContentFetcher:
    def __init__(
        self,
        profile_path: str | Path = "data/browser-profile",
        context_factory=None,
        channel: str = "chrome",
        navigation_timeout_ms: int = 60000,
    ):
        self.profile_path = str(profile_path)
        self.context_factory = context_factory or self._playwright_context_factory
        self.channel = channel
        self.navigation_timeout_ms = navigation_timeout_ms

    def fetch(self, url: str) -> ArticleContent:
        context = self.context_factory(
            user_data_dir=self.profile_path,
            headless=False,
            channel=self.channel,
        )
        try:
            page = context.new_page()
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.navigation_timeout_ms,
            )
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            text = _read_visible_page_text(page)
            response_status = getattr(
                response,
                "status",
                getattr(response, "status_code", 0),
            )
            return ArticleContent(
                final_url=str(page.url),
                http_status=int(response_status or 0),
                title=page.title() or None,
                extracted_text=text,
            )
        finally:
            context.close()

    def _playwright_context_factory(self, user_data_dir: str, headless: bool, channel: str):
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=headless,
                channel=channel,
            )
        except Exception:
            playwright.stop()
            raise
        return _PlaywrightContextHandle(context=context, playwright=playwright)


class _PlaywrightContextHandle:
    def __init__(self, context, playwright):
        self.context = context
        self.playwright = playwright

    def new_page(self):
        return self.context.new_page()

    def close(self):
        try:
            self.context.close()
        finally:
            self.playwright.stop()


class HybridArticleContentFetcher:
    def __init__(
        self,
        http_fetcher: ArticleContentFetcherProtocol,
        browser_fetcher: ArticleContentFetcherProtocol,
        browser_domains: tuple[str, ...],
    ):
        self.http_fetcher = http_fetcher
        self.browser_fetcher = browser_fetcher
        self.browser_domains = browser_domains

    def fetch(self, url: str) -> ArticleContent:
        host = urlparse(url).hostname or ""
        if any(host == domain or host.endswith(f".{domain}") for domain in self.browser_domains):
            return self.browser_fetcher.fetch(url)
        return self.http_fetcher.fetch(url)


def _read_visible_page_text(page) -> str:
    for selector in ("article", "main", "body"):
        try:
            text = page.locator(selector).inner_text(timeout=5000)
        except Exception:
            continue
        if text.strip():
            return text.strip()
    return ""
