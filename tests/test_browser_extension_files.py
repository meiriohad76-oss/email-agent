import json
from pathlib import Path
import subprocess
import textwrap


EXTENSION_DIR = Path("browser-extension")


def test_browser_extension_manifest_supports_configurable_pi_backend():
    manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["version"] == "0.1.16"
    assert "storage" in manifest["permissions"]
    assert "windows" in manifest["permissions"]
    assert "http://*/*" in manifest["host_permissions"]
    assert "https://*/*" in manifest["host_permissions"]
    assert "https://www.investing.com/*" in manifest["host_permissions"]
    assert manifest["options_page"] == "options.html"


def test_browser_extension_background_reads_api_base_from_storage():
    background = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")

    assert 'const DEFAULT_API_BASE = "http://127.0.0.1:8000"' in background
    assert "chrome.storage.local.get" in background
    assert "chrome.storage.sync" not in background
    assert "normalizeApiBase" in background
    assert "backendPassword" in background
    assert "X-Email-Article-Analyzer-Password" in background
    assert "`${apiBase}${path}`" in background


def test_browser_extension_options_page_saves_backend_url():
    options_html = (EXTENSION_DIR / "options.html").read_text(encoding="utf-8")
    options_js = (EXTENSION_DIR / "options.js").read_text(encoding="utf-8")

    assert "Backend URL" in options_html
    assert "Backend password" in options_html
    assert "http://192.168.1.50:8000" in options_html
    assert "chrome.storage.local.set" in options_js
    assert "chrome.storage.sync" not in options_js
    assert "backendPassword" in options_js
    assert "new URL(apiBase)" in options_js


def test_browser_extension_api_fetch_uses_local_storage_url_and_password_header():
    background_path = EXTENSION_DIR / "background.js"
    script = textwrap.dedent(
        f"""
        const fs = require("fs");
        const vm = require("vm");
        const code = fs.readFileSync({str(background_path)!r}, "utf8");
        const calls = [];
        const context = {{
          console,
          Headers,
          setTimeout: () => {{}},
          fetch: async (url, options) => {{
            calls.push({{
              url,
              password: options.headers.get("X-Email-Article-Analyzer-Password"),
            }});
            return {{ ok: true, json: async () => ({{ ok: true }}) }};
          }},
          chrome: {{
            storage: {{
              local: {{
                get: async (defaults) => ({{
                  ...defaults,
                  apiBase: "http://192.168.1.50:8000/",
                  backendPassword: "bridge-secret",
                }}),
              }},
            }},
            tabs: {{ get: async () => ({{ status: "complete" }}) }},
          }},
        }};
        vm.createContext(context);
        vm.runInContext(code, context);
        context.apiFetch("/api/browser-tasks/status").then(() => {{
          console.log(JSON.stringify(calls));
        }});
        """
    )
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    calls = json.loads(completed.stdout)
    assert calls[-1:] == [
        {
            "url": "http://192.168.1.50:8000/api/browser-tasks/status",
            "password": "bridge-secret",
        }
    ]


def test_browser_extension_options_saves_compatible_local_storage_keys():
    options_path = EXTENSION_DIR / "options.js"
    script = textwrap.dedent(
        f"""
        const fs = require("fs");
        const vm = require("vm");
        const code = fs.readFileSync({str(options_path)!r}, "utf8");
        const elements = {{
          "api-base": {{ value: "http://192.168.1.55:8000/" }},
          "backend-password": {{ value: " bridge-secret " }},
          "status": {{ textContent: "" }},
          "save-button": {{ addEventListener: () => {{}} }},
        }};
        const saved = [];
        const context = {{
          console,
          URL,
          document: {{
            getElementById: (id) => elements[id],
          }},
          chrome: {{
            storage: {{
              local: {{
                get: async (defaults) => defaults,
                set: async (payload) => {{ saved.push(payload); }},
              }},
            }},
          }},
        }};
        vm.createContext(context);
        vm.runInContext(code, context);
        context.saveOptions().then(() => {{
          console.log(JSON.stringify({{ saved, status: elements.status.textContent }}));
        }});
        """
    )
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload == {
        "saved": [
            {
                "apiBase": "http://192.168.1.55:8000",
                "backendPassword": "bridge-secret",
            }
        ],
        "status": "Saved.",
    }


def test_browser_extension_extracts_seeking_alpha_rating_labels_for_parser():
    result = _run_background_extraction(
        page_url="https://seekingalpha.com/symbol/AAPL/ratings/quant-ratings",
        title="AAPL Ratings",
        selector_texts={
            "body": (
                "Apple Inc.\n"
                "Quant Rating\nStrong Buy\n4.82\n"
                "Analysts Rating\nBuy\n4.11\n"
                "Wall Street Rating\nBuy\n4.35\n"
                "Wall Street Price Target\n$245.50"
            )
        },
    )

    assert "SA Quant Rating Strong Buy 4.82" in result["extracted_text"]
    assert "SA Analysts Rating Buy 4.11" in result["extracted_text"]
    assert "Wall Street Rating Buy 4.35" in result["extracted_text"]
    assert "Wall Street price target $245.50" in result["extracted_text"]


def test_browser_extension_extracts_zacks_rating_labels_for_parser():
    result = _run_background_extraction(
        page_url="https://www.zacks.com/stock/quote/AAPL",
        title="AAPL Quote",
        selector_texts={
            "body": (
                "Apple Inc.\n"
                "Zacks Rank\n"
                "#2 (Buy)\n"
                "Average Broker Recommendation\n"
                "1.42\n"
                "Price Target\n"
                "$260.00"
            )
        },
    )

    assert "Zacks Rank #2 (Buy)" in result["extracted_text"]
    assert "Average Broker Recommendation 1.42" in result["extracted_text"]
    assert "Price Target $260.00" in result["extracted_text"]


def test_browser_extension_uses_text_content_when_inner_text_is_empty_for_ratings():
    result = _run_background_extraction(
        page_url="https://seekingalpha.com/symbol/ANET/ratings/quant-ratings",
        title="ANET Ratings",
        selector_texts={
            "body": {
                "innerText": "",
                "textContent": (
                    "Arista Networks\n"
                    "Quant Rating\nStrong Buy\n4.61\n"
                    "Analysts Rating\nBuy\n4.07\n"
                    "Wall Street Price Target\n$122.50"
                ),
            }
        },
    )

    assert "SA Quant Rating Strong Buy 4.61" in result["extracted_text"]
    assert "SA Analysts Rating Buy 4.07" in result["extracted_text"]
    assert "Wall Street price target $122.50" in result["extracted_text"]


def test_browser_extension_prefers_substantial_visible_text_over_hidden_markup():
    visible = (
        "Boeing overview visible financial data "
        "Revenue 66.52B Net Income -11.82B Gross Profit Margin 4.1% "
        "Analysts Sentiment Buy Price Target 250.00"
    )
    result = _run_background_extraction(
        page_url="https://www.investing.com/equities/boeing-co",
        title="Boeing Stock Price Today",
        selector_texts={
            "body": {
                "innerText": visible,
                "textContent": visible + " Pardon our interruption Press and hold to verify " * 20,
            }
        },
    )

    assert "Pardon our interruption" not in result["extracted_text"]
    assert "Revenue 66.52B" in result["extracted_text"]


def test_browser_extension_normalizes_current_seeking_alpha_rating_labels():
    result = _run_background_extraction(
        page_url="https://seekingalpha.com/symbol/ANET/ratings/sell-side-ratings",
        title="ANET Sell Side Ratings",
        selector_texts={
            "body": (
                "Arista Networks\n"
                "Author Rating\nBuy\n4.02\n"
                "Sell Side Rating\nStrong Buy\n4.55\n"
                "Sell Side Price Target\n$129.00"
            )
        },
    )

    assert "SA Analysts Rating Buy 4.02" in result["extracted_text"]
    assert "Wall Street Rating Strong Buy 4.55" in result["extracted_text"]
    assert "Wall Street price target $129.00" in result["extracted_text"]


def test_browser_extension_normalizes_seeking_alpha_apostrophe_rating_labels():
    result = _run_background_extraction(
        page_url="https://seekingalpha.com/symbol/ANET/ratings/quant-ratings",
        title="ANET Quant Ratings",
        selector_texts={
            "body": (
                "ANET Quant Rating\nStrong Buy\n4.61\n"
                "SA Analysts' Rating\nBuy\n4.02\n"
                "Wall St. Analysts' Rating\nStrong Buy\n4.55\n"
                "Average Price Target\n$129.00"
            )
        },
    )

    assert "SA Quant Rating Strong Buy 4.61" in result["extracted_text"]
    assert "SA Analysts Rating Buy 4.02" in result["extracted_text"]
    assert "Wall Street Rating Strong Buy 4.55" in result["extracted_text"]
    assert "Wall Street price target $129.00" in result["extracted_text"]


def test_browser_extension_extraction_function_is_self_contained_for_chrome_injection():
    result = _run_standalone_injected_extraction(
        page_url="https://seekingalpha.com/symbol/ANET/ratings/quant-ratings",
        title="ANET Ratings",
        selector_texts={
            "body": (
                "Arista Networks\n"
                "Quant Rating\nStrong Buy\n4.61\n"
                "Sell Side Rating\nBuy\n4.32\n"
                "Sell Side Price Target\n$129.00"
            )
        },
    )

    assert "SA Quant Rating Strong Buy 4.61" in result["extracted_text"]
    assert "Wall Street Rating Buy 4.32" in result["extracted_text"]
    assert "Wall Street price target $129.00" in result["extracted_text"]


def test_browser_extension_includes_seeking_alpha_ssr_rating_data_for_parser():
    result = _run_standalone_injected_extraction(
        page_url="https://seekingalpha.com/symbol/AIS/ratings/quant-ratings",
        title="AIS Ratings",
        selector_texts={"body": "AIS Quant Rating\nVIEW RATINGS\nVIEW RATINGS"},
        extra_context="""
          window.SSR_DATA = {
            ratings: {
              quantRating: "Strong Buy",
              authorsRating: "Buy",
              sellSideRating: "Hold",
              priceTarget: "$83.25"
            }
          };
        """,
    )

    assert "SA_DATA SSR_DATA.ratings.quantRating = Strong Buy" in result["extracted_text"]
    assert "SA_DATA SSR_DATA.ratings.authorsRating = Buy" in result["extracted_text"]
    assert "SA_DATA SSR_DATA.ratings.sellSideRating = Hold" in result["extracted_text"]
    assert "SA_DATA SSR_DATA.ratings.priceTarget = $83.25" in result["extracted_text"]


def test_browser_extension_includes_seeking_alpha_json_script_rating_data():
    result = _run_standalone_injected_extraction(
        page_url="https://seekingalpha.com/symbol/CRDO/ratings/sell-side-ratings",
        title="CRDO Ratings",
        selector_texts={"body": "CRDO Ratings\nVIEW RATINGS"},
        query_selector_all={
            "script": [
                {
                    "textContent": json.dumps(
                        {
                            "props": {
                                "pageProps": {
                                    "currentQuantRating": {"rating": "Buy", "score": 3.88},
                                    "authorRatings": {"rating": "Hold", "score": 3.12},
                                    "sellSideRatings": {"rating": "Strong Buy", "score": 4.66},
                                    "priceTarget": {"average": "$269.81", "high": "$350.00"},
                                }
                            }
                        }
                    )
                }
            ]
        },
    )

    assert "SA_DATA SCRIPT_DATA[0].props.pageProps.currentQuantRating.rating = Buy" in result["extracted_text"]
    assert "SA_DATA SCRIPT_DATA[0].props.pageProps.currentQuantRating.score = 3.88" in result["extracted_text"]
    assert "SA_DATA SCRIPT_DATA[0].props.pageProps.sellSideRatings.rating = Strong Buy" in result["extracted_text"]
    assert "SA_DATA SCRIPT_DATA[0].props.pageProps.priceTarget.average = $269.81" in result["extracted_text"]


def test_browser_extension_extracts_zacks_rank_from_rank_widget_attributes():
    result = _run_standalone_injected_extraction(
        page_url="https://www.zacks.com/stock/quote/ONDS",
        title="ONDAS INC - ONDS - Stock Price Today - Zacks",
        selector_texts={"body": "Zacks Rank More Info\nQuote Overview\nStyle Scores"},
        query_selector_all={
            "[id*='rank' i], [class*='rank' i], [aria-label*='rank' i], [title*='rank' i]": [
                {
                    "innerText": "3-Hold",
                    "textContent": "3-Hold",
                    "attributes": {
                        "class": "rank_chip zacks_rank",
                        "title": "Zacks Rank #3 (Hold)",
                    },
                }
            ]
        },
    )

    assert "Zacks Rank #3 (Hold)" in result["extracted_text"]


def test_browser_extension_normalizes_zacks_visible_rank_dash_layout():
    result = _run_standalone_injected_extraction(
        page_url="https://www.zacks.com/stock/quote/ONDS",
        title="ONDAS INC - ONDS - Stock Price Today - Zacks",
        selector_texts={
            "body": "Zacks Rank:\n3-Hold\nStyle Scores:\nF Value | F Growth | B Momentum | F VGM"
        },
    )

    assert "Zacks Rank #3 (Hold)" in result["extracted_text"]


def test_browser_extension_includes_investing_search_result_links():
    scoped_selector = (
        ".js-inner-all-results-quotes-wrapper a[href*='/equities/'], "
        ".js-inner-all-results-quotes-wrapper a[href*='/etfs/'], "
        ".searchResultsMain .quatesTable a[href*='/equities/'], "
        ".searchResultsMain .quatesTable a[href*='/etfs/']"
    )
    result = _run_standalone_injected_extraction(
        page_url="https://www.investing.com/search/?q=AAPL",
        title="Search",
        selector_texts={"body": 'Search Results for "AAPL"'},
        query_selector_all={
            scoped_selector: [
                {
                    "innerText": "AAPL Apple Inc Stock - NASDAQ equities",
                    "textContent": "AAPL Apple Inc Stock - NASDAQ equities",
                    "attributes": {"href": "/equities/apple-computer-inc"},
                },
                {
                    "innerText": "AAPL Apple Inc CDR Stock - Toronto equities",
                    "textContent": "AAPL Apple Inc CDR Stock - Toronto equities",
                    "attributes": {"href": "/equities/apple-cdr"},
                },
            ]
        },
    )

    assert (
        "INVESTING_RESULT AAPL Apple Inc Stock - NASDAQ equities | "
        "/equities/apple-computer-inc"
    ) in result["extracted_text"]
    assert "/equities/apple-cdr" in result["extracted_text"]


def test_browser_extension_includes_investing_etf_search_result_links():
    scoped_selector = (
        ".js-inner-all-results-quotes-wrapper a[href*='/equities/'], "
        ".js-inner-all-results-quotes-wrapper a[href*='/etfs/'], "
        ".searchResultsMain .quatesTable a[href*='/equities/'], "
        ".searchResultsMain .quatesTable a[href*='/etfs/']"
    )
    result = _run_standalone_injected_extraction(
        page_url="https://www.investing.com/search/?q=QQQ",
        title="Search",
        selector_texts={"body": 'Search Results for "QQQ"'},
        query_selector_all={
            scoped_selector: [
                {
                    "innerText": "QQQ Invesco QQQ Trust ETF - NASDAQ etfs",
                    "textContent": "QQQ Invesco QQQ Trust ETF - NASDAQ etfs",
                    "attributes": {"href": "/etfs/powershares-qqqq"},
                },
            ]
        },
    )

    assert (
        "INVESTING_RESULT QQQ Invesco QQQ Trust ETF - NASDAQ etfs | "
        "/etfs/powershares-qqqq"
    ) in result["extracted_text"]


def test_browser_extension_retries_article_extraction_after_page_settle():
    background = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")

    assert "const EXTRACTION_ATTEMPTS =" in background
    assert "const EXTRACTION_RETRY_MS =" in background
    assert "async function extractArticleFromTab" in background
    assert "await sleep(EXTRACTION_RETRY_MS)" in background
    assert "function hasUsefulExtractedText(article)" in background
    assert "async function prepareTabForExtraction(tabId, url)" in background
    assert "window.scrollTo(0, document.body.scrollHeight)" in background
    assert "seekingalpha\\.com\\/symbol\\/[^/]+\\/ratings" in background
    assert "function isSeekingAlphaResearchPage" in background
    assert "income-statement" in background
    assert "Cash from Operations" in background
    assert "SA Quant Rating" in background
    assert "bestRating" not in background
    assert "currentQuantRating" in background
    assert "function isDynamicResearchTablePage" in background
    assert "EQUITY_RESEARCH_TABLE" in background
    assert "EQUITY_PAGE_UNAVAILABLE" in background
    assert "EQUITY_TABLE_MISSING" in background


def test_browser_extension_waits_for_a_real_investing_search_result():
    background = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")

    assert "investing\\.com\\/search\\/" in background
    assert "^INVESTING_RESULT\\s+.+\\|\\s+\\/(?:equities|etfs)\\/" in background


def test_browser_extension_contains_structured_equity_news_extraction():
    background = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")

    assert "function equityNewsListingText" in background
    assert "EQUITY_NEWS_ITEM" in background
    assert "author_rating" in background


def test_browser_extension_emits_structured_zacks_insider_transaction():
    background_path = EXTENSION_DIR / "background.js"
    script = textwrap.dedent(
        f"""
        const fs = require("fs");
        const vm = require("vm");
        const code = fs.readFileSync({str(background_path)!r}, "utf8");
        const backgroundContext = {{ console, fetch: async () => {{}}, setTimeout: () => {{}}, chrome: {{ storage: {{ local: {{ get: async (x) => x }} }}, tabs: {{ get: async () => ({{ status: "complete" }}) }} }} }};
        vm.createContext(backgroundContext);
        vm.runInContext(code, backgroundContext);
        const values = ["Delaet Ingrid", "Chief Regulatory Officer", "7/10/26", "DS", "Indirect", "COM", "4,367", "181.02", "790,514", "16,225"];
        const cells = values.map((value) => ({{ innerText: value, textContent: value }}));
        const headers = ["Filer's name", "Relationship /Title", "Tran Date", "Tran Type", "Owner Type", "Security Type", "Shares", "Price($)", "Tran Value($)", "Total Shares Owned"].map((value) => ({{ innerText: value, textContent: value }}));
        const row = {{ querySelectorAll: () => cells }};
        const table = {{ querySelectorAll: (selector) => selector === "thead th, thead td" ? headers : selector === "tbody tr" ? [row] : [] }};
        const body = {{ innerText: values.join(" ").repeat(3), textContent: values.join(" ").repeat(3) }};
        const pageContext = {{
          console,
          URL,
          window: {{ location: {{ href: "https://www.zacks.com/stock/research/NBIX/insider-transactions" }} }},
          document: {{
            title: "NBIX Insiders",
            querySelector: (selector) => selector === "body" ? body : null,
            querySelectorAll: (selector) => selector === "table" ? [table] : [],
          }},
        }};
        vm.createContext(pageContext);
        const result = vm.runInContext(`(${{backgroundContext.extractArticleText.toString()}})()`, pageContext);
        console.log(JSON.stringify(result));
        """
    )
    completed = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    result = json.loads(completed.stdout)

    marker = next(line for line in result["extracted_text"].splitlines() if line.startswith("EQUITY_INSIDER_TXN "))
    item = json.loads(marker.removeprefix("EQUITY_INSIDER_TXN "))
    assert item["transaction_date"] == "2026-07-10"
    assert item["transaction_code"] == "DS"
    assert item["shares"] == "4,367"
    assert item["shares_owned_after"] == "16,225"


def test_browser_extension_emits_structured_seeking_alpha_analysis_item():
    background_path = EXTENSION_DIR / "background.js"
    script = textwrap.dedent(
        f"""
        const fs = require("fs");
        const vm = require("vm");
        const code = fs.readFileSync({str(background_path)!r}, "utf8");
        const backgroundContext = {{ console, fetch: async () => {{}}, setTimeout: () => {{}}, chrome: {{ storage: {{ local: {{ get: async (x) => x }} }}, tabs: {{ get: async () => ({{ status: "complete" }}) }} }} }};
        vm.createContext(backgroundContext);
        vm.runInContext(code, backgroundContext);
        const primary = {{ innerText: "Neurocrine: pipeline upside remains underappreciated", textContent: "Neurocrine: pipeline upside remains underappreciated", getAttribute: (name) => name === "href" ? "/article/123-neurocrine" : null }};
        const author = {{ innerText: "Research Author", textContent: "Research Author", getAttribute: (name) => name === "href" ? "/author/research-author" : null }};
        const paragraph = {{ innerText: "The author argues that consensus omits two pipeline assets.", textContent: "The author argues that consensus omits two pipeline assets." }};
        const time = {{ textContent: "Thu, Jul 30", getAttribute: () => "2026-07-30" }};
        const card = {{
          innerText: "Neurocrine: pipeline upside remains underappreciated Author's rating: Buy Research Author Thu, Jul 30",
          textContent: "Neurocrine: pipeline upside remains underappreciated Author's rating: Buy Research Author Thu, Jul 30",
          querySelectorAll: (selector) => selector === "a[href]" ? [primary, author] : selector === "p" ? [paragraph] : [],
          querySelector: (selector) => selector === "time" ? time : null,
        }};
        const body = {{ innerText: card.innerText.repeat(3), textContent: card.textContent.repeat(3) }};
        const pageContext = {{
          console,
          URL,
          window: {{ location: {{ href: "https://seekingalpha.com/symbol/NBIX/analysis" }} }},
          document: {{
            title: "NBIX Analysis",
            querySelector: (selector) => selector === "body" ? body : selector === "article" ? card : null,
            querySelectorAll: (selector) => selector === "article, [role='article']" ? [card] : [],
          }},
        }};
        vm.createContext(pageContext);
        const result = vm.runInContext(`(${{backgroundContext.extractArticleText.toString()}})()`, pageContext);
        console.log(JSON.stringify(result));
        """
    )
    completed = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    result = json.loads(completed.stdout)

    marker = next(line for line in result["extracted_text"].splitlines() if line.startswith("EQUITY_NEWS_ITEM "))
    item = json.loads(marker.removeprefix("EQUITY_NEWS_ITEM "))
    assert item["content_type"] == "analysis"
    assert item["author"] == "Research Author"
    assert item["author_rating"] == "Buy"
    assert item["published_at"] == "2026-07-30"
    assert item["url"] == "https://seekingalpha.com/article/123-neurocrine"


def test_browser_extension_allows_large_seeking_alpha_rating_json_scripts():
    background = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")

    assert "raw.length > 3000000" in background
    assert "rating|score|rank|target|quant|author|sell|side|wall|analyst|forecast" in background


def _run_background_extraction(
    page_url: str,
    title: str,
    selector_texts: dict[str, str | dict[str, str]],
) -> dict:
    background_path = EXTENSION_DIR / "background.js"
    script = textwrap.dedent(
        f"""
        const fs = require("fs");
        const vm = require("vm");
        const code = fs.readFileSync({str(background_path)!r}, "utf8");
        const selectorTexts = {json.dumps(selector_texts)};
        const context = {{
          console,
          result: null,
          fetch: async () => {{ throw new Error("backend unavailable"); }},
          setTimeout: () => {{}},
          window: {{ location: {{ href: {page_url!r} }} }},
          document: {{
            title: {title!r},
            querySelector: (selector) => {{
              const value = selectorTexts[selector] || null;
              if (value === null) {{
                return null;
              }}
              if (typeof value === "string") {{
                return {{ innerText: value, textContent: value }};
              }}
              return {{
                innerText: value.innerText || "",
                textContent: value.textContent || "",
              }};
            }},
          }},
          chrome: {{
            storage: {{ local: {{ get: async (defaults) => defaults }} }},
            tabs: {{ get: async () => ({{ status: "complete" }}) }},
          }},
        }};
        vm.createContext(context);
        vm.runInContext(code, context);
        context.result = context.extractArticleText();
        console.log(JSON.stringify(context.result));
        """
    )
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _run_standalone_injected_extraction(
    page_url: str,
    title: str,
    selector_texts: dict[str, str | dict[str, str]],
    extra_context: str = "",
    query_selector_all: dict[str, list[dict[str, str]]] | None = None,
) -> dict:
    background_path = EXTENSION_DIR / "background.js"
    script = textwrap.dedent(
        f"""
        const fs = require("fs");
        const vm = require("vm");
        const code = fs.readFileSync({str(background_path)!r}, "utf8");
        const selectorTexts = {json.dumps(selector_texts)};
        const selectorAll = {json.dumps(query_selector_all or {})};
        const backgroundContext = {{
          console,
          fetch: async () => {{ throw new Error("backend unavailable"); }},
          setTimeout: () => {{}},
          chrome: {{
            storage: {{ local: {{ get: async (defaults) => defaults }} }},
            tabs: {{ get: async () => ({{ status: "complete" }}) }},
          }},
        }};
        vm.createContext(backgroundContext);
        vm.runInContext(code, backgroundContext);
        const injectedFunctionSource = backgroundContext.extractArticleText.toString();
        const pageContext = {{
          console,
          result: null,
          window: {{ location: {{ href: {page_url!r} }} }},
          document: {{
            title: {title!r},
            querySelector: (selector) => {{
              const value = selectorTexts[selector] || null;
              if (value === null) {{
                return null;
              }}
              if (typeof value === "string") {{
                return {{ innerText: value, textContent: value }};
              }}
              return {{
                innerText: value.innerText || "",
                textContent: value.textContent || "",
              }};
            }},
            querySelectorAll: (selector) => {{
              return (selectorAll[selector] || []).map((value) => ({{
                innerText: value.innerText || "",
                textContent: value.textContent || "",
                getAttribute: (name) => (value.attributes || {{}})[name] || null,
                attributes: Object.entries(value.attributes || {{}}).map(([name, attrValue]) => ({{
                  name,
                  value: attrValue,
                }})),
              }}));
            }},
          }},
        }};
        vm.createContext(pageContext);
        vm.runInContext({extra_context!r}, pageContext);
        pageContext.result = vm.runInContext(`(${{injectedFunctionSource}})()`, pageContext);
        console.log(JSON.stringify(pageContext.result));
        """
    )
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)
