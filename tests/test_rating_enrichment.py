from email_article_analyzer.rating_enrichment import (
    TickerRatingEnrichmentService,
    parse_seeking_alpha_ratings,
    parse_zacks_ratings,
    rating_enrichment_urls,
    required_enrichment_data_types,
    _research_page_without_data_reason,
    _unparsed_rating_failure_reason,
)
from email_article_analyzer.db import initialize_database
from email_article_analyzer.repositories import RunRepository


from pathlib import Path


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "rating_enrichment"


class FakeContent:
    final_url = "https://example.com/final"
    http_status = 200
    title = "Ratings"

    def __init__(self, text):
        self.extracted_text = text


class FakeFetcher:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        content = FakeContent(self.responses[url])
        if "investing.com" in url:
            content.final_url = url
        return content


def test_loaded_zacks_insider_page_without_transaction_table_is_not_applicable():
    reason = _research_page_without_data_reason(
        "zacks",
        "insider_transactions",
        "CNQ: Canadian Natural Resources - Insider Transations - Zacks.com",
        "Generic Zacks page content " * 200,
    )

    assert reason == "Zacks does not provide an insider-transaction table for this security"
    assert _research_page_without_data_reason(
        "zacks",
        "insider_transactions",
        "CNQ Insider Transactions - Zacks.com",
        "EQUITY_INSIDER_TXN {} " + "page content " * 300,
    ) is None
    assert _research_page_without_data_reason(
        "seeking_alpha",
        "options_chain",
        "Example options",
        'EQUITY_TABLE_MISSING {"provider":"seeking_alpha","data_type":"options_chain",'
        '"reason":"No qualifying data table rendered"}',
    ) == "No qualifying data table rendered"


def test_research_page_without_data_recognizes_provider_absence_signals():
    assert _research_page_without_data_reason(
        "seeking_alpha",
        "cash_flow_statement",
        "Cash Flow Statement",
        "SA_DATA SSR_DATA.symbol.response.meta.availableData.cash_flow = false",
    ) == "Seeking Alpha does not supply cash-flow statement data for this security"
    assert _research_page_without_data_reason(
        "investing_pro",
        "analysis",
        "Example Analysis & Opinion",
        "Example Analysis\nNo analysis for this asset\nSee other Stock Markets analysis",
    ) == "Investing.com does not supply analysis articles for this security"


def test_rating_enrichment_urls_include_sa_and_zacks_rating_pages():
    urls = rating_enrichment_urls("aapl")

    assert urls == [
        {
            "provider": "seeking_alpha",
            "data_type": "ratings",
            "url": "https://seekingalpha.com/symbol/AAPL/ratings/quant-ratings",
        },
        {
            "provider": "seeking_alpha",
            "data_type": "author_ratings",
            "url": "https://seekingalpha.com/symbol/AAPL/ratings/author-ratings",
        },
        {
            "provider": "seeking_alpha",
            "data_type": "sell_side_ratings",
            "url": "https://seekingalpha.com/symbol/AAPL/ratings/sell-side-ratings",
        },
        {
            "provider": "zacks",
            "data_type": "quote",
            "url": "https://www.zacks.com/stock/quote/AAPL",
        },
        {
            "provider": "zacks",
            "data_type": "price_target_forecast",
            "url": "https://www.zacks.com/stock/research/AAPL/price-target-stock-forecast",
        },
    ]


def test_parse_seeking_alpha_ratings_extracts_rating_scores_and_price_target():
    text = """
    Apple Inc. SA Quant Rating Strong Buy 4.82
    SA Analysts Rating Buy 4.11
    Wall Street Rating Buy 4.35
    Wall Street price target $245.50
    """

    snapshots = parse_seeking_alpha_ratings("AAPL", text)

    assert snapshots == [
        {
            "ticker": "AAPL",
            "provider": "seeking_alpha",
            "rating_type": "quant",
            "rating": "Strong Buy",
            "score": 4.82,
            "price_target": None,
            "currency": "USD",
            "source_text": "SA Quant Rating Strong Buy 4.82",
        },
        {
            "ticker": "AAPL",
            "provider": "seeking_alpha",
            "rating_type": "analysts",
            "rating": "Buy",
            "score": 4.11,
            "price_target": None,
            "currency": "USD",
            "source_text": "SA Analysts Rating Buy 4.11",
        },
        {
            "ticker": "AAPL",
            "provider": "seeking_alpha",
            "rating_type": "wall_street",
            "rating": "Buy",
            "score": 4.35,
            "price_target": None,
            "currency": "USD",
            "source_text": "Wall Street Rating Buy 4.35",
        },
        {
            "ticker": "AAPL",
            "provider": "seeking_alpha",
            "rating_type": "price_target",
            "rating": "Wall Street price target",
            "score": None,
            "price_target": 245.5,
            "currency": "USD",
            "source_text": "Wall Street price target $245.50",
        },
    ]


def test_parse_seeking_alpha_ratings_extracts_rating_without_score_from_page_data():
    text = """
    SA_DATA SSR_DATA.ratingData.quantRating = Strong Buy
    SA_DATA SSR_DATA.ratingData.authorsRating = Buy
    SA_DATA SSR_DATA.ratingData.sellSideRating = Hold
    SA_DATA SSR_DATA.forecast.priceTarget = $83.25
    """

    snapshots = parse_seeking_alpha_ratings("AIS", text)

    assert snapshots == [
        {
            "ticker": "AIS",
            "provider": "seeking_alpha",
            "rating_type": "quant",
            "rating": "Strong Buy",
            "score": None,
            "price_target": None,
            "currency": "USD",
            "source_text": "SA_DATA SSR_DATA.ratingData.quantRating = Strong Buy",
        },
        {
            "ticker": "AIS",
            "provider": "seeking_alpha",
            "rating_type": "analysts",
            "rating": "Buy",
            "score": None,
            "price_target": None,
            "currency": "USD",
            "source_text": "SA_DATA SSR_DATA.ratingData.authorsRating = Buy",
        },
        {
            "ticker": "AIS",
            "provider": "seeking_alpha",
            "rating_type": "wall_street",
            "rating": "Hold",
            "score": None,
            "price_target": None,
            "currency": "USD",
            "source_text": "SA_DATA SSR_DATA.ratingData.sellSideRating = Hold",
        },
        {
            "ticker": "AIS",
            "provider": "seeking_alpha",
            "rating_type": "price_target",
            "rating": "Wall Street price target",
            "score": None,
            "price_target": 83.25,
            "currency": "USD",
            "source_text": "priceTarget = $83.25",
        },
    ]


def test_parse_zacks_ratings_extracts_rank_and_price_target():
    text = """
    Zacks Rank #2 (Buy)
    Average Broker Recommendation 1.42
    Price Target $260.00
    """

    snapshots = parse_zacks_ratings("AAPL", text)

    assert snapshots == [
        {
            "ticker": "AAPL",
            "provider": "zacks",
            "rating_type": "rank",
            "rating": "Rank #2 Buy",
            "score": 2,
            "price_target": None,
            "currency": "USD",
            "source_text": "Zacks Rank #2 (Buy)",
        },
        {
            "ticker": "AAPL",
            "provider": "zacks",
            "rating_type": "price_target",
            "rating": "Zacks price target",
            "score": None,
            "price_target": 260.0,
            "currency": "USD",
            "source_text": "Price Target $260.00",
        },
    ]


def test_parse_zacks_ratings_extracts_visible_rank_dash_layout():
    text = """
    Zacks Rank:
    3-Hold
    Style Scores:
    F Value | F Growth | B Momentum | F VGM
    """

    snapshots = parse_zacks_ratings("ONDS", text)

    assert snapshots == [
        {
            "ticker": "ONDS",
            "provider": "zacks",
            "rating_type": "rank",
            "rating": "Rank #3 Hold",
            "score": 3,
            "price_target": None,
            "currency": "USD",
            "source_text": "Zacks Rank: 3-Hold",
            "style_scores": {
                "value": "F",
                "growth": "F",
                "momentum": "B",
                "vgm": "F",
            },
        }
    ]


def test_parse_zacks_ratings_extracts_research_price_target_forecast():
    text = """
    Average Price Target
    $276.85
    Highest Price Target
    $350.00
    Lowest Price Target
    $215.00
    Upside to Average Price Target
    3.29%
    Last Close
    268.03
    Analyst Price Targets (17)
    """

    snapshots = parse_zacks_ratings("CRDO", text)

    assert snapshots == [
        {
            "ticker": "CRDO",
            "provider": "zacks",
            "rating_type": "price_target",
            "rating": "Zacks price target",
            "score": None,
            "price_target": 276.85,
            "currency": "USD",
            "source_text": (
                "Average Price Target $276.85; Highest $350.00; "
                "Lowest $215.00; Upside 3.29%; Last Close $268.03"
            ),
            "price_target_high": 350.0,
            "price_target_low": 215.0,
            "price_target_upside_pct": 3.29,
            "source_reported_upside_pct": 3.29,
            "last_close": 268.03,
            "source_last_close": 268.03,
            "analyst_count": 17,
        }
    ]


def test_parse_seeking_alpha_extracts_sell_side_average_price_target_from_page():
    text = """
    Price Target
    Average Price Target
    269.81
    +13.37% Upside
    High: 350.00
    Low: 184.00
    """

    snapshots = parse_seeking_alpha_ratings("CRDO", text)

    assert snapshots == [
        {
            "ticker": "CRDO",
            "provider": "seeking_alpha",
            "rating_type": "price_target",
            "rating": "Wall Street price target",
            "score": None,
            "price_target": 269.81,
            "currency": "USD",
            "source_text": (
                "Average Price Target 269.81; High 350.00; "
                "Low 184.00; Upside 13.37%"
            ),
            "price_target_high": 350.0,
            "price_target_low": 184.0,
            "price_target_upside_pct": 13.37,
            "source_reported_upside_pct": 13.37,
            "implied_last_close_from_reported_upside": 237.99,
        }
    ]


def test_parse_seeking_alpha_ratings_extracts_visible_page_rating_labels():
    text = """
    Quant Rating
    Buy
    3.88
    SA Analysts' Rating
    Hold
    3.12
    Wall St. Analysts' Rating
    Strong Buy
    4.66
    """

    snapshots = parse_seeking_alpha_ratings("AAOI", text)

    assert snapshots[:3] == [
        {
            "ticker": "AAOI",
            "provider": "seeking_alpha",
            "rating_type": "quant",
            "rating": "Buy",
            "score": 3.88,
            "price_target": None,
            "currency": "USD",
            "source_text": "Quant Rating Buy 3.88",
        },
        {
            "ticker": "AAOI",
            "provider": "seeking_alpha",
            "rating_type": "analysts",
            "rating": "Hold",
            "score": 3.12,
            "price_target": None,
            "currency": "USD",
            "source_text": "SA Analysts' Rating Hold 3.12",
        },
        {
            "ticker": "AAOI",
            "provider": "seeking_alpha",
            "rating_type": "wall_street",
            "rating": "Strong Buy",
            "score": 4.66,
            "price_target": None,
            "currency": "USD",
            "source_text": "Wall St. Analysts' Rating Strong Buy 4.66",
        },
    ]


def test_parse_seeking_alpha_ratings_extracts_current_visible_sa_layout():
    text = """
    Quant Rating
    SA Analysts' Rating
    Wall St. Analysts' Rating
    Quant Rating
    ?
    HOLD
    RATING: HOLD
    2.82
    SA Analyst Rating
    BUY
    RATING: BUY
    3.83
    Wall St. Ratings
    ?
    BUY
    RATING: BUY
    4.09
    """

    snapshots = parse_seeking_alpha_ratings("AEM", text)

    assert [snapshot["rating_type"] for snapshot in snapshots[:3]] == [
        "quant",
        "analysts",
        "wall_street",
    ]
    assert [snapshot["rating"] for snapshot in snapshots[:3]] == ["Hold", "Buy", "Buy"]
    assert [snapshot["score"] for snapshot in snapshots[:3]] == [2.82, 3.83, 4.09]


def test_parse_seeking_alpha_ratings_extracts_json_like_rating_values():
    text = """
    "quantRating":"Hold","quantRatingScore":3.44
    "authorsRating":"Buy","authorsRatingScore":4.01
    "sellSideRating":"Strong Buy","sellSideRatingScore":4.72
    """

    snapshots = parse_seeking_alpha_ratings("AAOI", text)

    assert [snapshot["rating_type"] for snapshot in snapshots] == [
        "quant",
        "analysts",
        "wall_street",
    ]
    assert [snapshot["rating"] for snapshot in snapshots] == ["Hold", "Buy", "Strong Buy"]
    assert [snapshot["score"] for snapshot in snapshots] == [3.44, 4.01, 4.72]


def test_parse_seeking_alpha_ratings_extracts_nested_rating_score_fields():
    text = """
    SA_DATA SCRIPT_DATA.props.pageProps.currentQuantRating.rating = Buy
    SA_DATA SCRIPT_DATA.props.pageProps.currentQuantRating.score = 3.88
    SA_DATA SCRIPT_DATA.props.pageProps.authorRatings.rating = Hold
    SA_DATA SCRIPT_DATA.props.pageProps.authorRatings.score = 3.12
    SA_DATA SCRIPT_DATA.props.pageProps.sellSideRatings.rating = Strong Buy
    SA_DATA SCRIPT_DATA.props.pageProps.sellSideRatings.score = 4.66
    SA_DATA SCRIPT_DATA.props.pageProps.priceTarget.average = 269.81
    """

    snapshots = parse_seeking_alpha_ratings("CRDO", text)

    assert [snapshot["rating_type"] for snapshot in snapshots[:3]] == [
        "quant",
        "analysts",
        "wall_street",
    ]
    assert [snapshot["rating"] for snapshot in snapshots[:3]] == ["Buy", "Hold", "Strong Buy"]
    assert [snapshot["score"] for snapshot in snapshots[:3]] == [3.88, 3.12, 4.66]
    assert snapshots[3]["rating_type"] == "price_target"
    assert snapshots[3]["price_target"] == 269.81


def test_parse_seeking_alpha_crdo_rating_fixture_extracts_visible_scores():
    text = (FIXTURES_DIR / "seeking_alpha_crdo_rating_cards.txt").read_text(encoding="utf-8")

    snapshots = parse_seeking_alpha_ratings("CRDO", text)

    assert [snapshot["rating_type"] for snapshot in snapshots] == [
        "quant",
        "analysts",
        "wall_street",
    ]
    assert [snapshot["rating"] for snapshot in snapshots] == [
        "Strong Buy",
        "Buy",
        "Strong Buy",
    ]
    assert [snapshot["score"] for snapshot in snapshots] == [4.37, 4.06, 4.66]


def test_rating_enrichment_urls_capture_investing_immediately_after_mapping():
    urls = rating_enrichment_urls(
        "ANET",
        include_research=True,
        investing_url="https://www.investing.com/equities/arista-networks",
    )

    assert urls[0] == {
        "provider": "investing_pro",
        "data_type": "overview",
        "url": "https://www.investing.com/equities/arista-networks",
    }
    assert urls[1]["provider"] == "investing_pro"
    assert next(index for index, item in enumerate(urls) if item["provider"] == "seeking_alpha") == 9


def test_etf_investing_urls_exclude_stock_only_research_routes():
    urls = rating_enrichment_urls(
        "QQQ",
        asset_type="etf",
        include_research=True,
        investing_url="https://www.investing.com/etfs/powershares-qqqq",
    )
    investing = [item for item in urls if item["provider"] == "investing_pro"]

    assert [item["data_type"] for item in investing] == [
        "overview",
        "news",
        "analysis",
        "options_chain",
    ]
    assert all("/etfs/powershares-qqqq" in item["url"] for item in investing)


def test_parse_zacks_forecast_captures_style_scores_and_industry_rank_on_rank_record():
    text = """
    Zacks Rank #4 (Sell)
    Style Scores: More Info C Value | B Growth | B Momentum | B VGM
    Industry Rank: More Info Bottom 14% (211 out of 246)
    Industry: Food - Miscellaneous
    Average Price Target $20.70
    """

    snapshots = parse_zacks_ratings("DANOY", text)
    rank = next(snapshot for snapshot in snapshots if snapshot["rating_type"] == "rank")

    assert rank["style_scores"] == {
        "value": "C",
        "growth": "B",
        "momentum": "B",
        "vgm": "B",
    }
    assert rank["industry_rank"] == "Bottom 14% (211 out of 246)"


def test_rating_enrichment_urls_include_structured_research_pages_and_investing_mapping():
    urls = rating_enrichment_urls(
        "AAPL",
        include_research=True,
        investing_url="https://www.investing.com/equities/apple-computer-inc",
    )

    types = {(item["provider"], item["data_type"]) for item in urls}
    assert ("seeking_alpha", "valuation") in types
    assert ("seeking_alpha", "peers") in types
    assert ("seeking_alpha", "news") in types
    assert ("seeking_alpha", "analysis") in types
    assert ("seeking_alpha", "options_chain") in types
    assert ("zacks", "detailed_estimates") in types
    assert ("zacks", "insider_transactions") in types
    assert ("zacks", "options_chain") in types
    assert ("zacks", "greeks_montage") in types
    assert ("investing_pro", "forecast") in types
    assert ("investing_pro", "ratios") in types
    assert ("investing_pro", "news") in types
    assert ("investing_pro", "analysis") in types
    assert ("investing_pro", "options_chain") in types
    detailed = next(item for item in urls if item["provider"] == "zacks" and item["data_type"] == "detailed_estimates")
    assert detailed["url"] == "https://www.zacks.com/stock/quote/AAPL/detailed-earning-estimates"


def test_rating_enrichment_service_auto_discovers_and_caches_investing_mapping(tmp_path):
    mapping_path = tmp_path / "investing-map.csv"
    fetcher = FakeFetcher(
        {
            "https://www.investing.com/search/?q=AAPL": (
                "INVESTING_RESULT AAPL Apple Inc Equity - NASDAQ equities | /equities/apple-computer-inc"
            ),
            "https://www.investing.com/equities/apple-computer-inc": """
                Key Statistics
                Company's Health
                Good
                Fair Value
                Undervalued
                Fair Price
                $225.00
                Upside
                12.50%
                Analysts Sentiment
                Buy
                Price Target
                $240.00
                P/E Ratio
                28.4
            """,
        }
    )
    saved = []

    class FakeRepository:
        def save_ticker_enrichment(self, **kwargs):
            saved.append(kwargs)
            return len(saved)

        def delete_ticker_enrichment(self, **kwargs):
            return 0

    service = TickerRatingEnrichmentService(
        fetcher=fetcher,
        repository=FakeRepository(),
        include_research=True,
        investing_mapping_path=mapping_path,
    )

    result = service.enrich_ticker(
        run_id=7,
        ticker="AAPL",
        company_name="Apple Inc.",
        target_keys={("investing_pro", "overview")},
    )

    assert fetcher.calls == [
        "https://www.investing.com/search/?q=AAPL",
        "https://www.investing.com/equities/apple-computer-inc",
    ]
    assert result == {"attempted": 1, "saved": 1, "failed": 0}
    mapping = next(item for item in saved if item["provider"] == "investing_pro" and item["data_type"] == "mapping")
    assert mapping["source_url"] == "https://www.investing.com/equities/apple-computer-inc"
    overview = next(item for item in saved if item["provider"] == "investing_pro" and item["data_type"] == "overview")
    assert overview["data"]["financial_health"] == "Good"
    assert service.investing_urls["AAPL"] == "https://www.investing.com/equities/apple-computer-inc"
    assert "AAPL" in mapping_path.read_text(encoding="utf-8-sig")
    assert "https://www.investing.com/equities/apple-computer-inc" in mapping_path.read_text(encoding="utf-8-sig")


def test_rating_enrichment_service_auto_discovers_investing_etf_mapping(tmp_path):
    mapping_path = tmp_path / "investing-map.csv"
    fetcher = FakeFetcher(
        {
            "https://www.investing.com/search/?q=QQQ": (
                "INVESTING_RESULT QQQ Invesco QQQ Trust ETF - NASDAQ etfs | /etfs/powershares-qqqq"
            ),
            "https://www.investing.com/etfs/powershares-qqqq": """
                Key Statistics
                Company's Health
                Good
                Fair Value
                Fair
                Fair Price
                $580.00
            """,
        }
    )
    saved = []

    class FakeRepository:
        def save_ticker_enrichment(self, **kwargs):
            saved.append(kwargs)
            return len(saved)

        def delete_ticker_enrichment(self, **kwargs):
            return 0

    service = TickerRatingEnrichmentService(
        fetcher=fetcher,
        repository=FakeRepository(),
        include_research=True,
        investing_mapping_path=mapping_path,
    )

    result = service.enrich_ticker(
        run_id=7,
        ticker="QQQ",
        asset_type="etf",
        company_name="Invesco QQQ Trust",
        target_keys={("investing_pro", "overview")},
    )

    assert fetcher.calls == [
        "https://www.investing.com/search/?q=QQQ",
        "https://www.investing.com/etfs/powershares-qqqq",
    ]
    assert result == {"attempted": 1, "saved": 1, "failed": 0}
    mapping = next(item for item in saved if item["provider"] == "investing_pro" and item["data_type"] == "mapping")
    assert mapping["source_url"] == "https://www.investing.com/etfs/powershares-qqqq"
    overview = next(item for item in saved if item["provider"] == "investing_pro" and item["data_type"] == "overview")
    assert overview["data"]["financial_health"] == "Good"


def test_missing_investing_mapping_is_not_applicable(tmp_path):
    fetcher = FakeFetcher({"https://www.investing.com/search/?q=SMEGF": "No matching instruments"})
    saved = []

    class FakeRepository:
        def save_ticker_enrichment(self, **kwargs):
            saved.append(kwargs)
            return len(saved)

        def delete_ticker_enrichment(self, **kwargs):
            return 0

    service = TickerRatingEnrichmentService(
        fetcher=fetcher,
        repository=FakeRepository(),
        include_research=True,
        investing_mapping_path=tmp_path / "investing-map.csv",
    )

    service.enrich_ticker(
        run_id=80,
        ticker="SMEGF",
        target_keys={("investing_pro", "mapping")},
    )

    mapping = next(item for item in saved if item["data_type"] == "mapping")
    assert mapping["status"] == "not_applicable"
    assert mapping["failure_reason"] is None


def test_sell_side_page_without_price_target_records_provider_absence(tmp_path):
    url = "https://seekingalpha.com/symbol/ANCTF/ratings/sell-side-ratings"
    fetcher = FakeFetcher({url: "Wall Street Rating Buy 4.2"})
    saved = []

    class FakeRepository:
        def save_ticker_enrichment(self, **kwargs):
            saved.append(kwargs)
            return len(saved)

        def delete_ticker_enrichment(self, **kwargs):
            return 0

    service = TickerRatingEnrichmentService(fetcher=fetcher, repository=FakeRepository())
    result = service.enrich_ticker(
        run_id=80,
        ticker="ANCTF",
        target_keys={("seeking_alpha", "sell_side_ratings")},
    )

    assert result == {"attempted": 1, "saved": 2, "failed": 0}
    price_target = next(item for item in saved if item["data_type"] == "price_target")
    assert price_target["status"] == "not_applicable"
    assert price_target["failure_reason"] is None


def test_explicit_sell_side_unavailability_wins_over_unrelated_rating_text():
    url = "https://seekingalpha.com/symbol/ANCTF/ratings/sell-side-ratings"
    fetcher = FakeFetcher(
        {
            url: (
                "Wall St. Analysts' Rating We currently have no Wall St. Ratings on this stock "
                "SA Analysts HOLD RATING: HOLD 3.00"
            )
        }
    )
    saved = []
    deleted = []

    class FakeRepository:
        def save_ticker_enrichment(self, **kwargs):
            saved.append(kwargs)
            return len(saved)

        def delete_ticker_enrichment(self, **kwargs):
            deleted.append(kwargs)
            return 1

    service = TickerRatingEnrichmentService(fetcher=fetcher, repository=FakeRepository())
    result = service.enrich_ticker(
        run_id=80,
        ticker="ANCTF",
        target_keys={("seeking_alpha", "sell_side_ratings")},
    )

    assert result == {"attempted": 1, "saved": 1, "failed": 0}
    assert saved[0]["data_type"] == "sell_side_ratings"
    assert saved[0]["status"] == "not_applicable"
    assert {item["data_type"] for item in deleted} == {
        "sell_side_ratings",
        "wall_street",
        "price_target",
    }


def test_investing_redirect_to_different_instrument_is_rejected(tmp_path):
    mapping_path = tmp_path / "investing-map.csv"

    class RedirectingFetcher(FakeFetcher):
        def fetch(self, url):
            content = super().fetch(url)
            if url.endswith("/equities/apple-computer-inc"):
                content.final_url = "https://www.investing.com/equities/microsoft-corp"
            return content

    fetcher = RedirectingFetcher(
        {
            "https://www.investing.com/search/?q=AAPL": (
                "INVESTING_RESULT AAPL Apple Inc Stock - NASDAQ equities | "
                "/equities/apple-computer-inc"
            ),
            "https://www.investing.com/equities/apple-computer-inc": "Key Statistics Fair Value $225",
        }
    )
    saved = []

    class FakeRepository:
        def save_ticker_enrichment(self, **kwargs):
            saved.append(kwargs)
            return len(saved)

        def delete_ticker_enrichment(self, **kwargs):
            return 0

    service = TickerRatingEnrichmentService(
        fetcher=fetcher,
        repository=FakeRepository(),
        include_research=True,
        investing_mapping_path=mapping_path,
    )

    result = service.enrich_ticker(
        run_id=7,
        ticker="AAPL",
        asset_type="stock",
        company_name="Apple Inc",
        target_keys={("investing_pro", "overview")},
    )

    assert result == {"attempted": 1, "saved": 0, "failed": 1}
    overview = next(
        item for item in saved
        if item["provider"] == "investing_pro" and item["data_type"] == "overview"
    )
    assert overview["status"] == "failed"
    assert "redirected away" in overview["failure_reason"]


def test_rating_enrichment_urls_include_investing_pages_for_etfs():
    urls = rating_enrichment_urls(
        "QQQ",
        asset_type="etf",
        include_research=True,
        investing_url="https://www.investing.com/etfs/powershares-qqqq",
    )

    types = {(item["provider"], item["data_type"]) for item in urls}
    assert ("investing_pro", "overview") in types
    assert ("investing_pro", "news") in types
    assert ("zacks", "price_target_forecast") not in types
    assert ("seeking_alpha", "valuation") not in types


def test_investing_research_page_suffix_precedes_instrument_query_string():
    urls = rating_enrichment_urls(
        "CNQ",
        include_research=True,
        investing_url="https://www.investing.com/equities/canadian-natural-resources?cid=20255",
    )

    by_type = {
        item["data_type"]: item["url"]
        for item in urls
        if item["provider"] == "investing_pro"
    }
    assert by_type["overview"] == "https://www.investing.com/equities/canadian-natural-resources?cid=20255"
    assert by_type["ratios"] == "https://www.investing.com/equities/canadian-natural-resources-ratios?cid=20255"
    assert by_type["forecast"] == "https://www.investing.com/equities/canadian-natural-resources-consensus-estimates?cid=20255"


def test_required_enrichment_types_include_expanded_research_contract():
    required = required_enrichment_data_types(
        asset_type="stock",
        include_polygon=False,
        include_research=True,
        include_investing=True,
    )

    assert "seeking_alpha:valuation_metrics" in required
    assert "seeking_alpha:peer_comparison" in required
    assert "seeking_alpha:news_items" in required
    assert "seeking_alpha:analysis_items" in required
    assert "seeking_alpha:options_chain" in required
    assert "zacks:detailed_estimates" in required
    assert "zacks:insider_transactions" in required
    assert "zacks:greeks_montage" in required
    assert "investing_pro:forecast" in required
    assert "investing_pro:ratios" in required
    assert "investing_pro:news_items" in required
    assert "investing_pro:analysis_items" in required
    assert "investing_pro:options_chain" in required


def test_parse_seeking_alpha_crdo_sell_side_fixture_extracts_target_range():
    text = (FIXTURES_DIR / "seeking_alpha_crdo_sell_side.txt").read_text(encoding="utf-8")

    snapshots = parse_seeking_alpha_ratings("CRDO", text)

    assert snapshots == [
        {
            "ticker": "CRDO",
            "provider": "seeking_alpha",
            "rating_type": "price_target",
            "rating": "Wall Street price target",
            "score": None,
            "price_target": 269.81,
            "currency": "USD",
            "source_text": (
                "Average Price Target 269.81; High 350.00; "
                "Low 184.00; Upside 13.37%"
            ),
            "price_target_high": 350.0,
            "price_target_low": 184.0,
            "price_target_upside_pct": 13.37,
            "source_reported_upside_pct": 13.37,
            "implied_last_close_from_reported_upside": 237.99,
        }
    ]


def test_parse_seeking_alpha_price_target_does_not_match_followers_as_low():
    text = """
    SLB Summary Follow 120.15K followers $48.91
    Price Target
    Average Price Target 62.00
    +26.76% Upside
    Chart annotations summary Average: 62.00 Low: 43.00 High: 71.00
    """

    target = next(
        item
        for item in parse_seeking_alpha_ratings("SLB", text)
        if item["rating_type"] == "price_target"
    )

    assert target["price_target"] == 62.0
    assert target["price_target_low"] == 43.0
    assert target["price_target_high"] == 71.0
    assert target["price_target_upside_pct"] == 26.76


def test_parse_zacks_ratings_extracts_positive_signed_source_upside():
    text = """
    Average Price Target
    $276.85
    Highest Price Target
    $350.00
    Lowest Price Target
    $215.00
    Upside to Average Price Target
    +3.29%
    Last Close
    268.03
    """

    snapshots = parse_zacks_ratings("CRDO", text)

    assert snapshots[0]["source_reported_upside_pct"] == 3.29


def test_parse_zacks_crdo_quote_fixture_extracts_rank():
    text = (FIXTURES_DIR / "zacks_crdo_quote.txt").read_text(encoding="utf-8")

    snapshots = parse_zacks_ratings("CRDO", text)

    assert snapshots == [
        {
            "ticker": "CRDO",
            "provider": "zacks",
            "rating_type": "rank",
            "rating": "Rank #3 Hold",
            "score": 3,
            "price_target": None,
            "currency": "USD",
            "source_text": "Zacks Rank: 3-Hold",
            "style_scores": {
                "value": "F",
                "growth": "F",
                "momentum": "B",
                "vgm": "F",
            },
        }
    ]


def test_parse_zacks_crdo_price_target_fixture_extracts_full_target_snapshot():
    text = (FIXTURES_DIR / "zacks_crdo_price_target.txt").read_text(encoding="utf-8")

    snapshots = parse_zacks_ratings("CRDO", text)

    assert snapshots == [
        {
            "ticker": "CRDO",
            "provider": "zacks",
            "rating_type": "price_target",
            "rating": "Zacks price target",
            "score": None,
            "price_target": 276.85,
            "currency": "USD",
            "source_text": (
                "Average Price Target $276.85; Highest $350.00; "
                "Lowest $215.00; Upside 3.29%; Last Close $268.03"
            ),
            "price_target_high": 350.0,
            "price_target_low": 215.0,
            "price_target_upside_pct": 3.29,
            "source_reported_upside_pct": 3.29,
            "last_close": 268.03,
            "source_last_close": 268.03,
            "analyst_count": 17,
        }
    ]


def test_rating_enrichment_service_fetches_pages_and_persists_snapshots(tmp_path):
    urls = rating_enrichment_urls("AAPL")
    fetcher = FakeFetcher(
        {
            urls[0]["url"]: "SA Quant Rating Strong Buy 4.82",
            urls[1]["url"]: "SA Analysts Rating Buy 4.11",
            urls[2]["url"]: "Wall Street Rating Buy 4.35 Wall Street price target $245.50",
            urls[3]["url"]: "Zacks Rank #2 (Buy) Price Target $260.00",
            urls[4]["url"]: (
                "Average Price Target $276.85 Highest Price Target $350.00 "
                "Lowest Price Target $215.00 Upside to Average Price Target 3.29% "
                "Last Close 268.03 Analyst Price Targets (17)"
            ),
        }
    )
    saved = []

    class FakeRepository:
        def save_ticker_enrichment(self, **kwargs):
            saved.append(kwargs)
            return len(saved)

        def delete_ticker_enrichment(self, **kwargs):
            return 0

    service = TickerRatingEnrichmentService(fetcher=fetcher, repository=FakeRepository())

    result = service.enrich_ticker(run_id=7, ticker="AAPL")

    assert fetcher.calls == [item["url"] for item in urls]
    assert result == {"attempted": 5, "saved": 7, "failed": 0}
    assert saved[0]["run_id"] == 7
    assert saved[0]["ticker"] == "AAPL"
    assert saved[0]["provider"] == "seeking_alpha"
    assert saved[0]["data_type"] == "quant"
    assert saved[0]["data"]["rating"] == "Strong Buy"
    zacks_targets = [
        item["data"]
        for item in saved
        if item["provider"] == "zacks" and item["data_type"] == "price_target"
    ]
    assert zacks_targets[-1]["price_target"] == 276.85
    assert zacks_targets[-1]["price_target_high"] == 350.0


def test_rating_enrichment_service_can_retry_only_selected_source_pages():
    urls = rating_enrichment_urls("AAPL")
    target = next(item for item in urls if item["provider"] == "zacks" and item["data_type"] == "quote")
    fetcher = FakeFetcher({target["url"]: "Zacks Rank #2 (Buy) Price Target $260.00"})
    saved = []

    class FakeRepository:
        def save_ticker_enrichment(self, **kwargs):
            saved.append(kwargs)
            return len(saved)

        def delete_ticker_enrichment(self, **kwargs):
            return 0

    service = TickerRatingEnrichmentService(fetcher=fetcher, repository=FakeRepository())

    result = service.enrich_ticker(
        run_id=7,
        ticker="AAPL",
        target_keys={("zacks", "quote")},
    )

    assert fetcher.calls == [target["url"]]
    assert result == {"attempted": 1, "saved": 2, "failed": 0}
    assert {item["provider"] for item in saved} == {"zacks"}


def test_blocked_zacks_estimates_retry_uses_forecast_fallback_without_claiming_full_tables():
    forecast_url = "https://www.zacks.com/stock/research/DANOY/price-target-stock-forecast"
    fetcher = FakeFetcher(
        {
            forecast_url: (
                "Zacks Rank #4 (Sell) "
                "Style Scores: C Value | B Growth | B Momentum | B VGM "
                "Average Price Target $20.70"
            )
        }
    )
    saved = []

    class FakeRepository:
        def save_ticker_enrichment(self, **kwargs):
            saved.append(kwargs)
            return len(saved)

        def delete_ticker_enrichment(self, **kwargs):
            return 1

    service = TickerRatingEnrichmentService(
        fetcher=fetcher,
        repository=FakeRepository(),
        include_research=True,
    )

    result = service.enrich_ticker(
        run_id=51,
        ticker="DANOY",
        target_keys={("zacks", "detailed_estimates")},
        zacks_forecast_for_detailed_estimates=True,
    )

    assert fetcher.calls == [forecast_url]
    assert result == {"attempted": 1, "saved": 2, "failed": 0}
    substitute = next(item for item in saved if item["data_type"] == "detailed_estimates")
    assert substitute["status"] == "not_applicable"
    assert substitute["source_url"] == "https://example.com/final"
    assert "earnings_estimates" in substitute["data"]["missing_fields"]
    rank = next(item for item in saved if item["data_type"] == "rank")
    assert rank["data"]["style_scores"]["growth"] == "B"


def test_successful_semantic_enrichments_satisfy_completeness_check(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    repo = RunRepository(db_path)
    run_id = repo.create_run("gpt-5.4", "gpt-5.4-mini")
    required_types = required_enrichment_data_types(asset_type="stock", include_polygon=True)
    providers_by_type = {
        "polygon:previous_close": ("polygon", "previous_close"),
        "seeking_alpha:quant": ("seeking_alpha", "quant"),
        "seeking_alpha:analysts": ("seeking_alpha", "analysts"),
        "seeking_alpha:wall_street": ("seeking_alpha", "wall_street"),
        "seeking_alpha:price_target": ("seeking_alpha", "price_target"),
        "zacks:rank": ("zacks", "rank"),
        "zacks:price_target": ("zacks", "price_target"),
    }
    for semantic_type in required_types:
        provider, data_type = providers_by_type[semantic_type]
        repo.save_ticker_enrichment(
            run_id=run_id,
            ticker="AAPL",
            provider=provider,
            data_type=data_type,
            data={"rating_type": semantic_type},
        )

    assert repo.has_complete_ticker_enrichments(
        run_id,
        "AAPL",
        required_data_types=required_types,
    )


def test_complete_enrichment_requires_both_sa_and_zacks_price_targets(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    repo = RunRepository(db_path)
    run_id = repo.create_run("gpt-5.4", "gpt-5.4-mini")
    required_types = required_enrichment_data_types(asset_type="stock", include_polygon=False)
    for provider, data_type in [
        ("seeking_alpha", "quant"),
        ("seeking_alpha", "analysts"),
        ("seeking_alpha", "wall_street"),
        ("seeking_alpha", "price_target"),
        ("zacks", "rank"),
    ]:
        repo.save_ticker_enrichment(
            run_id=run_id,
            ticker="AAPL",
            provider=provider,
            data_type=data_type,
            data={"rating_type": data_type},
        )

    assert not repo.has_complete_ticker_enrichments(
        run_id,
        "AAPL",
        required_data_types=required_types,
    )


def test_not_applicable_source_pages_satisfy_semantic_completeness_aliases(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    repo = RunRepository(db_path)
    run_id = repo.create_run("gpt-5.4", "gpt-5.4-mini")
    unavailable_pages = [
        ("seeking_alpha", "ratings"),
        ("seeking_alpha", "author_ratings"),
        ("seeking_alpha", "sell_side_ratings"),
        ("zacks", "quote"),
        ("zacks", "price_target_forecast"),
        ("investing_pro", "analysis"),
    ]
    for provider, data_type in unavailable_pages:
        repo.save_ticker_enrichment(
            run_id=run_id,
            ticker="ADR",
            provider=provider,
            data_type=data_type,
            data={"reason": "Provider does not supply this page"},
            status="not_applicable",
        )

    assert repo.has_complete_ticker_enrichments(
        run_id,
        "ADR",
        required_data_types={
            "seeking_alpha:quant",
            "seeking_alpha:analysts",
            "seeking_alpha:wall_street",
            "seeking_alpha:price_target",
            "zacks:rank",
            "zacks:price_target",
            "investing_pro:analysis_items",
        },
    )


def test_rating_enrichment_service_persists_polygon_previous_close_when_configured(tmp_path):
    urls = rating_enrichment_urls("AAPL")
    fetcher = FakeFetcher({url["url"]: "" for url in urls})
    saved = []

    class FakeRepository:
        def save_ticker_enrichment(self, **kwargs):
            saved.append(kwargs)
            return len(saved)

        def delete_ticker_enrichment(self, **kwargs):
            return 0

    class FakePolygonClient:
        def __init__(self):
            self.calls = []

        def previous_close(self, ticker):
            self.calls.append(ticker)
            return {"ticker": ticker, "last_close": 123.45, "source": "polygon_previous_close"}

    polygon_client = FakePolygonClient()
    service = TickerRatingEnrichmentService(
        fetcher=fetcher,
        repository=FakeRepository(),
        polygon_client=polygon_client,
    )

    result = service.enrich_ticker(run_id=7, ticker="AAPL")

    assert polygon_client.calls == ["AAPL"]
    assert result == {"attempted": 6, "saved": 1, "failed": 5}
    assert saved[0] == {
        "run_id": 7,
        "ticker": "AAPL",
        "provider": "polygon",
        "data_type": "previous_close",
        "data": {"ticker": "AAPL", "last_close": 123.45, "source": "polygon_previous_close"},
    }


def test_rating_enrichment_service_clears_stale_target_failures_after_success(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    repo = RunRepository(db_path)
    run_id = repo.create_run("gpt-5.4", "gpt-5.4-mini")
    urls = rating_enrichment_urls("AAPL")
    repo.save_ticker_enrichment(
        run_id=run_id,
        ticker="AAPL",
        provider="seeking_alpha",
        data_type="ratings",
        data={},
        source_url=urls[0]["url"],
        status="failed",
        failure_reason="No visible article text extracted",
    )
    repo.save_ticker_enrichment(
        run_id=run_id,
        ticker="AAPL",
        provider="zacks",
        data_type="quote",
        data={},
        source_url=urls[3]["url"],
        status="failed",
        failure_reason="No visible article text extracted",
    )
    fetcher = FakeFetcher(
        {
            urls[0]["url"]: "SA Quant Rating Strong Buy 4.82",
            urls[1]["url"]: "",
            urls[2]["url"]: "Wall Street Rating Buy 4.35 Wall Street price target $245.50",
            urls[3]["url"]: "Zacks Rank #2 (Buy) Price Target $260.00",
            urls[4]["url"]: "",
        }
    )
    service = TickerRatingEnrichmentService(fetcher=fetcher, repository=repo)

    result = service.enrich_ticker(run_id=run_id, ticker="AAPL")
    enrichments = repo.list_ticker_enrichments(run_id)

    assert result == {"attempted": 5, "saved": 5, "failed": 2}
    assert not any(
        item["provider"] == "seeking_alpha"
        and item["data_type"] == "ratings"
        and item["status"] == "failed"
        for item in enrichments
    )
    assert not any(
        item["provider"] == "zacks"
        and item["data_type"] == "quote"
        and item["status"] == "failed"
        for item in enrichments
    )
    assert any(
        item["provider"] == "seeking_alpha"
        and item["data_type"] == "quant"
        and item["status"] == "ready"
        for item in enrichments
    )
    assert any(
        item["provider"] == "zacks"
        and item["data_type"] == "rank"
        and item["status"] == "ready"
        for item in enrichments
    )


def test_rating_enrichment_service_records_failure_when_page_has_no_parsable_snapshot(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    repo = RunRepository(db_path)
    run_id = repo.create_run("gpt-5.4", "gpt-5.4-mini")
    urls = rating_enrichment_urls("ANET")
    fetcher = FakeFetcher(
        {
            urls[0]["url"]: "Before we continue... Press & Hold to confirm you are a human",
            urls[1]["url"]: "",
            urls[2]["url"]: "",
            urls[3]["url"]: "",
            urls[4]["url"]: "",
        }
    )
    service = TickerRatingEnrichmentService(fetcher=fetcher, repository=repo)

    result = service.enrich_ticker(run_id=run_id, ticker="ANET")
    enrichments = repo.list_ticker_enrichments(run_id)

    assert result == {"attempted": 5, "saved": 0, "failed": 5}
    assert enrichments[0]["ticker"] == "ANET"
    assert enrichments[0]["provider"] == "seeking_alpha"
    assert enrichments[0]["data_type"] == "author_ratings"
    assert enrichments[0]["status"] == "failed"
    assert enrichments[0]["failure_reason"] == "No rating snapshot parsed from page text"
    assert enrichments[0]["data"] == {
        "page_title": "Ratings",
        "text_sample": "",
        "text_char_count": 0,
    }


def test_rating_enrichment_service_classifies_blocked_or_locked_rating_pages(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    repo = RunRepository(db_path)
    run_id = repo.create_run("gpt-5.4", "gpt-5.4-mini")
    urls = rating_enrichment_urls("CRDO")
    fetcher = FakeFetcher(
        {
            urls[0]["url"]: "Go Premium to see CRDO Quant Rating VIEW RATINGS",
            urls[1]["url"]: "Access to this page has been denied Press & Hold to confirm you are a human",
            urls[2]["url"]: "Before we continue Press & Hold to confirm you are a human",
            urls[3]["url"]: (
                "Pardon Our Interruption. Something about your browser made us think you were a bot. "
                "Most Viewed Stocks on Zacks.com"
            ),
            urls[4]["url"]: "Request unsuccessful. Incapsula incident ID: 123",
        }
    )
    service = TickerRatingEnrichmentService(fetcher=fetcher, repository=repo)

    result = service.enrich_ticker(run_id=run_id, ticker="CRDO")
    enrichments = repo.list_ticker_enrichments(run_id)

    assert result == {"attempted": 5, "saved": 0, "failed": 5}
    reasons = {item["data_type"]: item["failure_reason"] for item in enrichments}
    assert reasons["price_target_forecast"] == "Rating page blocked by source bot verification"
    assert reasons["ratings"] == "Rating page is locked or premium-gated"
    assert reasons["author_ratings"] == "Rating page blocked by source bot verification"
    assert reasons["sell_side_ratings"] == "Rating page blocked by source bot verification"
    assert reasons["quote"] == "Rating page blocked by source bot verification"


def test_rating_enrichment_service_does_not_classify_loaded_zacks_quote_as_bot(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    repo = RunRepository(db_path)
    run_id = repo.create_run("gpt-5.4", "gpt-5.4-mini")
    urls = rating_enrichment_urls("ONDS")
    fetcher = FakeFetcher(
        {
            urls[0]["url"]: "",
            urls[1]["url"]: "",
            urls[2]["url"]: "",
            urls[3]["url"]: (
                "Zacks Rank More Info\n"
                "Skip to main content\n"
                "Home Stocks Funds Crypto Earnings Screening Finance Portfolio\n"
                "ONDAS INC - ONDS - Stock Price Today - Zacks\n"
                "Most Viewed Stocks on Zacks.com\n"
                "Request unsuccessful. Incapsula incident ID: embedded-widget\n"
            ),
            urls[4]["url"]: "",
        }
    )
    service = TickerRatingEnrichmentService(fetcher=fetcher, repository=repo)

    service.enrich_ticker(run_id=run_id, ticker="ONDS")

    quote = next(
        item
        for item in repo.list_ticker_enrichments(run_id)
        if item["provider"] == "zacks" and item["data_type"] == "quote"
    )
    assert quote["failure_reason"] == "No rating snapshot parsed from page text"


def test_rating_enrichment_service_classifies_source_coverage_unavailable(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    repo = RunRepository(db_path)
    run_id = repo.create_run("gpt-5.4", "gpt-5.4-mini")
    urls = rating_enrichment_urls("ETF")
    fetcher = FakeFetcher(
        {
            urls[0]["url"]: "ETF Quant Rating is not available. Not enough data.",
            urls[1]["url"]: "No ratings available for this symbol.",
            urls[2]["url"]: "SA_DATA showRatings.sell_side_rating = false",
            urls[3]["url"]: "No analyst coverage for ETF",
            urls[4]["url"]: "ETF price target not covered",
        }
    )
    service = TickerRatingEnrichmentService(fetcher=fetcher, repository=repo)

    result = service.enrich_ticker(run_id=run_id, ticker="ETF")
    enrichments = repo.list_ticker_enrichments(run_id)

    assert result == {"attempted": 5, "saved": 5, "failed": 0}
    assert {item["status"] for item in enrichments} == {"not_applicable"}
    assert {item["failure_reason"] for item in enrichments} == {None}
    assert {
        item["data"]["reason"] for item in enrichments
    } == {"Rating data unavailable from source coverage"}


def test_unparsed_failure_reason_identifies_transport_and_availability_pages():
    assert _unparsed_rating_failure_reason("Forbidden", "403 Forbidden") == "Source access blocked (HTTP 403)"
    assert _unparsed_rating_failure_reason("404 Page Not Found", "Error 404") == "Source page unavailable (HTTP 404)"
    assert _unparsed_rating_failure_reason("Please check back soon", "Temporarily down for maintenance") == "Source temporarily unavailable"
    assert _unparsed_rating_failure_reason(
        "Performing security verification while the website verifies you are not a bot",
        "Just a moment...",
    ) == "Rating page blocked by source bot verification"
    assert _unparsed_rating_failure_reason("Search", "Zacks Search Results") == "Rating data unavailable from source coverage"
    assert (
        _unparsed_rating_failure_reason(
            "Revenue Growth 5.01% RATING: NOT COVERED",
            "ANCTF Growth Grade",
            "growth",
        )
        == "No rating snapshot parsed from page text"
    )
