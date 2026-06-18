from email_article_analyzer.article_content import ArticleContentFetcher


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
