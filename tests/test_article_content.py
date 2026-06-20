from email_article_analyzer.article_content import (
    ArticleContentFetcher,
    BrowserArticleContentFetcher,
    HybridArticleContentFetcher,
)


class FakeResponse:
    status_code = 200
    url = "https://example.com/final"
    text = """
    <html>
      <head><title>NVDA raises guidance</title><script>ignore()</script></head>
      <body>
        <nav>Navigation</nav>
        <article>
          <h1>NVDA raises guidance</h1>
          <p>Nvidia raised its revenue outlook.</p>
          <p>Gross margin expanded to 75%.</p>
        </article>
      </body>
    </html>
    """

    def raise_for_status(self):
        return None


class FakeHttpClient:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return FakeResponse()


def test_article_content_fetcher_extracts_title_and_readable_text_from_html():
    client = FakeHttpClient()
    fetcher = ArticleContentFetcher(http_client=client)

    content = fetcher.fetch("https://example.com/article")

    assert client.calls[0]["url"] == "https://example.com/article"
    assert client.calls[0]["follow_redirects"] is True
    assert content.final_url == "https://example.com/final"
    assert content.http_status == 200
    assert content.title == "NVDA raises guidance"
    assert "Nvidia raised its revenue outlook." in content.extracted_text
    assert "Gross margin expanded to 75%." in content.extracted_text
    assert "Navigation" not in content.extracted_text
    assert "ignore()" not in content.extracted_text


class FakeLocator:
    def __init__(self, text):
        self.text = text

    def inner_text(self, timeout):
        return self.text


class FakePage:
    url = "https://seekingalpha.com/article/1"

    def __init__(self):
        self.calls = []

    def goto(self, url, wait_until, timeout):
        self.calls.append(("goto", url, wait_until, timeout))
        return FakeResponse()

    def wait_for_load_state(self, state, timeout):
        self.calls.append(("wait_for_load_state", state, timeout))

    def title(self):
        return "Seeking Alpha Story"

    def locator(self, selector):
        self.calls.append(("locator", selector))
        return FakeLocator("Authenticated article text")


class FakeBrowserContext:
    def __init__(self):
        self.page = FakePage()
        self.closed = False

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


def test_browser_article_content_fetcher_uses_visible_persistent_chrome_context(tmp_path):
    calls = {}
    context = FakeBrowserContext()

    def context_factory(user_data_dir, headless, channel):
        calls["user_data_dir"] = user_data_dir
        calls["headless"] = headless
        calls["channel"] = channel
        return context

    fetcher = BrowserArticleContentFetcher(
        profile_path=tmp_path / "browser-profile",
        context_factory=context_factory,
    )

    content = fetcher.fetch("https://seekingalpha.com/article/1")

    assert calls == {
        "user_data_dir": str(tmp_path / "browser-profile"),
        "headless": False,
        "channel": "chrome",
    }
    assert ("goto", "https://seekingalpha.com/article/1", "domcontentloaded", 60000) in context.page.calls
    assert ("locator", "article") in context.page.calls
    assert context.closed is True
    assert content.final_url == "https://seekingalpha.com/article/1"
    assert content.http_status == 200
    assert content.title == "Seeking Alpha Story"
    assert content.extracted_text == "Authenticated article text"


def test_hybrid_article_content_fetcher_routes_seeking_alpha_to_browser():
    class FakeFetcher:
        def __init__(self, label):
            self.label = label
            self.calls = []

        def fetch(self, url):
            self.calls.append(url)
            return self.label

    http_fetcher = FakeFetcher("http")
    browser_fetcher = FakeFetcher("browser")
    fetcher = HybridArticleContentFetcher(
        http_fetcher=http_fetcher,
        browser_fetcher=browser_fetcher,
        browser_domains=("seekingalpha.com",),
    )

    assert fetcher.fetch("https://seekingalpha.com/article/1") == "browser"
    assert fetcher.fetch("https://example.com/article") == "http"
    assert browser_fetcher.calls == ["https://seekingalpha.com/article/1"]
    assert http_fetcher.calls == ["https://example.com/article"]
