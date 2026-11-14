from fastapi.testclient import TestClient

from email_article_analyzer.db import initialize_database
from email_article_analyzer.api.runs import _rating_data_for_report
from email_article_analyzer.application import create_app
from email_article_analyzer.report_pdf_export import build_run_html_report
from email_article_analyzer.repositories import GmailDiscoveryRepository, RunRepository, WatchlistRepository


import re


def _plain_text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def sample_run_payload():
    run = {
        "id": 7,
        "status": "completed",
        "extraction_model": "gpt-5.4",
        "summary_model": "gpt-5.4-mini",
        "started_at": "2026-06-22 17:16:12",
        "completed_at": "2026-06-22 17:25:10",
    }
    counts = {"gmail_messages": 2, "article_links": 2}
    events = [
        {"severity": "info", "event_type": "run_completed", "stage": "completion"},
    ]
    articles = [
        {
            "subject": "Apple gets a new target",
            "source_key": "seeking_alpha",
            "normalized_url": "https://seekingalpha.com/article/1",
            "content": {
                "fetch_status": "fetched",
                "title": "Apple gets a new target",
                "text_char_count": 2400,
                "failure_reason": None,
            },
            "analysis": {
                "summary": "Apple demand and services margins improved.",
                "stance": "buy_watch",
                "sentiment": "bullish",
                "recommendation": "buy",
                "confidence": 0.81,
                "supporting_evidence": ["Services margin expanded", "Raised demand view"],
                "mentioned_ticker_details": [{"ticker": "AAPL", "in_portfolio": True}],
                "mentioned_tickers": ["AAPL"],
                "price_targets": [
                    {
                        "ticker": "AAPL",
                        "target_price": 250,
                        "currency": "USD",
                        "timeframe": "12 months",
                        "source_text": "target raised to $250",
                    }
                ],
                "actionable_data": [
                    {
                        "ticker": "AAPL",
                        "theme_summary": (
                            "The article's central thesis is that improving services economics and demand "
                            "support a more constructive view of Apple."
                        ),
                        "key_points": ["Services margins expanded", "The demand outlook was raised"],
                        "recommendation": "buy",
                        "source_recommendation_text": (
                            "The author recommends buying Apple, with a $250 target over 12 months."
                        ),
                        "catalysts": ["Services margin expansion"],
                        "risks": ["China demand"],
                        "investor_actions": [
                            "Compare the implied return with Apple's current valuation before changing exposure."
                        ],
                        "follow_up_checks": [
                            "Track services margins and China demand in the next earnings release."
                        ],
                    }
                ],
                "actionable_signals": [
                    {
                        "ticker": "AAPL",
                        "signal_type": "guidance",
                        "signal": "Revenue outlook",
                        "value": "raised guide",
                        "direction": "positive",
                        "timeframe": "FY",
                        "source_text": "Raised demand view",
                    }
                ],
            },
        },
        {
            "subject": "Microsoft risk case",
            "source_key": "seeking_alpha",
            "normalized_url": "https://seekingalpha.com/article/2",
            "content": {
                "fetch_status": "fetched",
                "title": "Microsoft risk case",
                "text_char_count": 1800,
                "failure_reason": None,
            },
            "analysis": {
                "summary": "The author argues valuation risk is elevated.",
                "stance": "sell_watch",
                "sentiment": "bearish",
                "recommendation": "sell",
                "confidence": 0.92,
                "supporting_evidence": ["Multiple remains high", "Growth is slowing"],
                "mentioned_ticker_details": [{"ticker": "MSFT", "in_portfolio": False}],
                "mentioned_tickers": ["MSFT"],
                "price_targets": [],
                "actionable_data": [{"ticker": "MSFT", "risks": ["Valuation compression"]}],
            },
        },
    ]
    return run, counts, events, articles


def test_build_run_html_report_uses_modern_pdf_design_sections():
    run, counts, events, articles = sample_run_payload()

    html = build_run_html_report(run, counts, events, articles)

    assert "Daily Stock Article Intelligence" in html
    assert "BLUF - most actionable recommendations" in html
    assert "Executive summary" in html
    assert "statband" in html
    assert "Unified ticker review" in html
    assert "Non-portfolio opportunities and risks" not in html
    assert "Run-level synthesis" not in html
    assert "Detailed article appendix" not in html
    assert "AAPL" in html
    assert "MSFT" not in html
    assert "Buy Watch" in html
    assert "Sell Watch" not in html
    assert "Article analysis model gpt-5.4-mini" in html
    assert "Extraction gpt-5.4" not in html
    assert "target raised to $250" in html
    assert "{{" not in html
    assert "<sc-for" not in html
    assert html.index("BLUF - most actionable recommendations") < html.index("Executive summary")


def test_build_run_html_report_includes_ticker_action_cards_and_provider_gaps():
    run, counts, events, articles = sample_run_payload()
    articles[0]["analysis"]["mentioned_ticker_details"][0].update(
        {
            "company_name": "Apple Inc.",
            "sector": "Technology",
            "priority": "core",
            "notes": "Large position",
            "polygon_reference": {
                "name": "Apple Inc.",
                "type": "CS",
                "market": "stocks",
                "locale": "us",
            },
            "asset_type": "stock",
        }
    )

    html = build_run_html_report(run, counts, events, articles)

    assert "Unified ticker review" in html
    assert "Apple Inc." in html
    assert "Asset: stock" in html
    text = _plain_text(html)
    assert "Article consensus: bullish / buy" in text
    assert "SA Quant: source page not fetched" in text
    assert "SA Analysts: source page not fetched" in text
    assert "SA Wall Street: source page not fetched" in text
    assert "Zacks Rank: source page not fetched" in text
    assert "Zacks target: source page not fetched" in text
    assert "Polygon reference: CS / stocks / us" in text
    assert "Upside/downside: needs last close" in text
    assert "Key signals: Guidance: Revenue outlook / raised guide / positive" in text
    assert "Suggested action: Review immediately" in html
    assert "source link" in html


def test_build_run_html_report_renders_detailed_actionable_article_brief():
    run, counts, events, articles = sample_run_payload()

    text = _plain_text(build_run_html_report(run, counts, events, articles))

    assert "central thesis is that improving services economics" in text
    assert "Key points: 1. Services margins expanded 2. The demand outlook was raised" in text
    assert "Article recommendation: The author recommends buying Apple" in text
    assert "Investor actions: 1. Compare the implied return" in text
    assert "Follow up: 1. Track services margins and China demand" in text


def test_build_run_html_report_bluf_prioritizes_clear_ticker_actions():
    run, counts, events, articles = sample_run_payload()

    html = build_run_html_report(run, counts, events, articles)
    text = _plain_text(html)

    assert "BLUF - most actionable recommendations" in text
    assert "AAPL Research now bullish / buy article read with 81% confidence" in text
    assert "See unified ticker section for evidence and source links" in text


def test_build_run_html_report_bluf_surfaces_rating_conflicts_before_buy_ideas():
    run, counts, events, articles = sample_run_payload()
    articles[0]["analysis"]["rating_snapshots"] = [
        {
            "ticker": "AAPL",
            "provider": "zacks",
            "rating_type": "rank",
            "rating": "Rank #4 Sell",
            "score": 4,
        }
    ]

    html = build_run_html_report(run, counts, events, articles)
    text = _plain_text(html)

    assert "AAPL Resolve conflict Article read is Buy Watch, but Zacks rank Rank #4 Sell (4) is bearish" in text


def test_build_run_html_report_keeps_articles_inside_ticker_sections_without_global_appendix():
    run, counts, events, articles = sample_run_payload()
    articles[1]["analysis"]["mentioned_ticker_details"][0]["in_portfolio"] = True

    html = build_run_html_report(run, counts, events, articles)

    assert "Detailed article appendix" not in html
    assert html.count("Apple gets a new target") == 1
    assert html.count("Microsoft risk case") == 1
    assert html.index('<span class="mono">AAPL</span>') < html.index("Apple gets a new target")
    assert html.index('<span class="mono">MSFT</span>') < html.index("Microsoft risk case")


def test_build_run_html_report_excludes_mention_only_tickers_from_unified_sections():
    run, counts, events, articles = sample_run_payload()
    articles[0]["analysis"]["summary"] = (
        "The article is primarily about Apple demand, Apple margins, and Apple services growth."
    )
    articles[0]["analysis"]["mentioned_ticker_details"] = [
        {"ticker": "AAPL", "in_portfolio": True},
        {"ticker": "MSFT", "in_portfolio": True},
    ]
    articles[0]["analysis"]["mentioned_tickers"] = ["AAPL", "MSFT"]
    articles[0]["analysis"]["actionable_data"] = [
        {
            "ticker": "AAPL",
            "recommendation": "buy",
            "catalysts": ["Apple services margin expansion"],
            "risks": ["Apple China demand"],
        }
    ]

    html = build_run_html_report(run, counts, events, articles)
    text = _plain_text(html)

    assert '<span class="mono">AAPL</span>' in html
    assert '<span class="mono">MSFT</span>' not in html
    assert "Apple services margin expansion" in text
    assert "primarily about Apple demand" not in text


def test_build_run_html_report_excludes_secondary_context_mentions_from_ticker_sections():
    run, counts, events, articles = sample_run_payload()
    articles[0]["content"]["title"] = "Apple customer demand improves (NASDAQ:AAPL)"
    articles[0]["analysis"]["mentioned_ticker_details"] = [
        {"ticker": "AAPL", "in_portfolio": True},
        {"ticker": "MSFT", "in_portfolio": True},
    ]
    articles[0]["analysis"]["mentioned_tickers"] = ["AAPL", "MSFT"]
    articles[0]["analysis"]["actionable_data"].append(
        {
            "ticker": "MSFT",
            "recommendation": "watch",
            "evidence": ["Microsoft is mentioned only as a customer demand source."],
            "risks": ["No standalone Microsoft recommendation is supplied."],
        }
    )

    html = build_run_html_report(run, counts, events, articles)

    assert '<span class="mono">AAPL</span>' in html
    assert '<span class="mono">MSFT</span>' not in html
    assert "Microsoft is mentioned only as a customer demand source" not in html


def test_build_run_html_report_keeps_ticker_information_out_of_side_tables():
    run, counts, events, articles = sample_run_payload()
    events.append(
        {
            "event_type": "run_report_synthesized",
            "details": {
                "priority_tickers": [
                    {
                        "ticker": "AAPL",
                        "priority": "high",
                        "reason": "Do not render this outside the ticker card.",
                    }
                ]
            },
        }
    )

    html = build_run_html_report(run, counts, events, articles)

    assert "Run-level synthesis" not in html
    assert "Priority tickers" not in html
    assert "Do not render this outside the ticker card" not in html
    assert "Non-portfolio opportunities and risks" not in html


def test_build_run_html_report_sorts_unified_ticker_cards_alphabetically():
    run, counts, events, articles = sample_run_payload()
    articles[1]["analysis"]["mentioned_ticker_details"][0]["in_portfolio"] = True
    articles[1]["analysis"]["confidence"] = 0.97

    html = build_run_html_report(run, counts, events, articles)

    aapl_index = html.index('<span class="mono">AAPL</span>')
    msft_index = html.index('<span class="mono">MSFT</span>')
    assert aapl_index < msft_index


def test_build_run_html_report_uses_extracted_sa_and_zacks_ratings():
    run, counts, events, articles = sample_run_payload()
    articles[0]["analysis"]["mentioned_ticker_details"][0].update(
        {
            "company_name": "Apple Inc.",
            "polygon_reference": {"type": "CS", "market": "stocks", "locale": "us"},
            "asset_type": "stock",
        }
    )
    articles[0]["analysis"]["rating_snapshots"] = [
        {
            "ticker": "AAPL",
            "provider": "seeking_alpha",
            "rating_type": "quant",
            "rating": "Hold",
            "score": 3.2,
            "price_target": None,
            "currency": "USD",
            "source_text": "Quant Hold 3.2",
        },
        {
            "ticker": "AAPL",
            "provider": "seeking_alpha",
            "rating_type": "wall_street",
            "rating": "Buy",
            "score": 4.1,
            "price_target": 245,
            "currency": "USD",
            "source_text": "Wall Street Buy with $245 target",
        },
        {
            "ticker": "AAPL",
            "provider": "zacks",
            "rating_type": "rank",
            "rating": "Rank #2 Buy",
            "score": 2,
            "price_target": 260,
            "currency": "USD",
            "source_text": "Zacks Rank #2 Buy, target $260",
        },
    ]

    html = build_run_html_report(run, counts, events, articles)

    text = _plain_text(html)
    assert "SA Quant: Hold (3.2)" in text
    assert "SA Wall Street: Buy (4.1)" in text
    assert "Zacks Rank: Rank #2 Buy (2)" in text
    assert "Zacks target: source page not fetched" in text


def test_build_run_html_report_distinguishes_article_ratings_from_unfetched_source_pages():
    run, counts, events, articles = sample_run_payload()
    articles[0]["analysis"]["mentioned_ticker_details"][0].update(
        {
            "company_name": "Apple Inc.",
            "polygon_reference": {"type": "CS", "market": "stocks", "locale": "us"},
            "asset_type": "stock",
        }
    )
    articles[0]["analysis"]["rating_snapshots"] = [
        {
            "ticker": "AAPL",
            "provider": "seeking_alpha",
            "rating_type": "quant",
            "rating": "Strong Buy",
            "score": 4.57,
            "price_target": None,
            "currency": "USD",
            "source_text": "Quant Strong Buy 4.57",
        }
    ]

    html = build_run_html_report(run, counts, events, articles)

    text = _plain_text(html)
    assert "SA Quant: Strong Buy (4.57) (article)" in text
    assert "SA Analysts: source page not fetched" in text
    assert "Zacks Rank: source page not fetched" in text
    assert "Zacks target: source page not fetched" in text


def test_build_run_html_report_marks_failed_fetch_and_etf_not_applicable():
    run, counts, events, articles = sample_run_payload()
    articles[0]["analysis"]["mentioned_ticker_details"][0].update(
        {
            "company_name": "Apple Inc.",
            "polygon_reference": {"type": "CS", "market": "stocks", "locale": "us"},
            "asset_type": "stock",
        }
    )
    articles[1]["analysis"]["mentioned_ticker_details"] = [
        {
            "ticker": "QQQ",
            "in_portfolio": True,
            "company_name": "Invesco QQQ",
            "polygon_reference": {"type": "ETF", "market": "stocks", "locale": "us"},
            "asset_type": "etf",
        }
    ]
    articles[1]["analysis"]["mentioned_tickers"] = ["QQQ"]
    articles[1]["analysis"]["actionable_data"] = [{"ticker": "QQQ", "risks": ["Index concentration"]}]

    html = build_run_html_report(
        run,
        counts,
        events,
        articles,
        rating_data_by_ticker={
            "AAPL": [
                {
                    "ticker": "AAPL",
                    "provider": "seeking_alpha",
                    "rating_type": "quant",
                    "status": "failed",
                    "failure_reason": "No rating snapshot parsed from page text",
                },
                {
                    "ticker": "AAPL",
                    "provider": "zacks",
                    "rating_type": "price_target",
                    "status": "failed",
                    "failure_reason": "Rating page blocked by source verification",
                },
            ]
        },
    )
    qqq_section = html[
        html.index('<span class="mono">QQQ</span>') : html.index("</article>", html.index('<span class="mono">QQQ</span>'))
    ]

    text = _plain_text(html)
    qqq_text = _plain_text(qqq_section)
    assert "SA Quant: fetch failed" in text
    assert "Zacks target: fetch failed" in text
    assert "<b>SA target:</b><span class='action-value'>not applicable for ETF</span>" in qqq_section
    assert "SA Wall Street: source page not fetched" in qqq_text
    assert "Zacks Rank: source page not fetched" in qqq_text
    assert "Zacks target: not applicable for ETF" in qqq_text


def test_rating_data_for_report_preserves_failed_source_fetch_status(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_repo = RunRepository(db_path)
    run_id = run_repo.create_run("gpt-extract", "gpt-summary")
    run_repo.save_ticker_enrichment(
        run_id=run_id,
        ticker="AAPL",
        provider="seeking_alpha",
        data_type="quant",
        data={},
        status="failed",
        failure_reason="No rating snapshot parsed from page text",
    )

    rating_data = _rating_data_for_report(run_repo, run_id)

    assert rating_data["AAPL"] == [
        {
            "ticker": "AAPL",
            "provider": "seeking_alpha",
            "rating_type": "quant",
            "status": "failed",
            "failure_reason": "No rating snapshot parsed from page text",
        }
    ]


def test_build_run_html_report_uses_persisted_ticker_enrichment_ratings():
    run, counts, events, articles = sample_run_payload()
    articles[0]["analysis"]["mentioned_ticker_details"][0].update(
        {
            "company_name": "Apple Inc.",
            "polygon_reference": {"type": "CS", "market": "stocks", "locale": "us"},
            "asset_type": "stock",
        }
    )

    html = build_run_html_report(
        run,
        counts,
        events,
        articles,
        rating_data_by_ticker={
            "AAPL": [
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
                    "provider": "zacks",
                    "rating_type": "rank",
                    "rating": "Rank #2 Buy",
                    "score": 2,
                    "price_target": None,
                    "currency": "USD",
                    "source_text": "Zacks Rank #2 (Buy)",
                },
            ],
        },
    )

    text = _plain_text(html)
    assert "SA Quant: Strong Buy (4.82)" in text
    assert "Zacks Rank: Rank #2 Buy (2)" in text


def test_build_run_html_report_surfaces_investing_pro_enrichment():
    run, counts, events, articles = sample_run_payload()
    articles[0]["analysis"]["mentioned_ticker_details"][0].update(
        {
            "company_name": "Apple Inc.",
            "polygon_reference": {"type": "CS", "market": "stocks", "locale": "us"},
            "asset_type": "stock",
        }
    )
    articles[0]["analysis"]["price_targets"] = []

    html = build_run_html_report(
        run,
        counts,
        events,
        articles,
        market_data_by_ticker={"AAPL": {"last_close": 200.0}},
        rating_data_by_ticker={
            "AAPL": [
                {
                    "ticker": "AAPL",
                    "provider": "investing_pro",
                    "rating_type": "overview",
                    "rating": "Good",
                    "financial_health": "Good",
                    "fair_value": {"raw": "$225.00", "value": 225.0, "unit": None},
                    "analyst_sentiment": "Buy",
                    "analyst_price_target": {"raw": "$240.00", "value": 240.0, "unit": None},
                },
                {
                    "ticker": "AAPL",
                    "provider": "investing_pro",
                    "rating_type": "forecast",
                    "rating": "Buy",
                    "rating_count": 25,
                    "analyst_target_average": 250.0,
                    "analyst_target_low": 180.0,
                    "analyst_target_high": 300.0,
                    "fair_value": 230.0,
                    "fair_value_upside_pct": 15.0,
                    "fair_value_uncertainty": "LOW",
                    "fair_value_model_count": 14,
                },
                {
                    "ticker": "AAPL",
                    "provider": "investing_pro",
                    "rating_type": "ratios",
                    "rating": "Company vs industry ratios",
                    "categories": {
                        "valuation_ratios": [
                            {
                                "metric": "P/E RatioTTM",
                                "company": {"raw": "28.4", "value": 28.4, "unit": None},
                                "industry": {"raw": "21.2", "value": 21.2, "unit": None},
                            }
                        ],
                        "profitability": [
                            {
                                "metric": "Gross marginTTM",
                                "company": {"raw": "44.2%", "value": 44.2, "unit": "percent"},
                                "industry": {"raw": "36.0%", "value": 36.0, "unit": "percent"},
                            }
                        ],
                    },
                },
            ],
        },
    )

    text = _plain_text(html)
    assert "InvestingPro health: Good; fair value USD 225; analysts Buy" in text
    assert "InvestingPro fair value: USD 230 (Polygon +15.0%; source +15.0%; uncertainty LOW; 14 models)" in text
    assert "InvestingPro analyst target: USD 250 (Polygon +25.0%; range USD 180-300; 25 ratings; Buy)" in text
    assert "InvestingPro ratios: Valuation P/E RatioTTM: 28.4 vs industry 21.2; Profitability Gross marginTTM: 44.2% vs industry 36%" in text
    assert "INVESTING FAIR VALUE: USD 230 (Polygon +15.0%; source +15.0%; uncertainty LOW; 14 models)." in text


def test_build_run_html_report_calculates_polygon_last_close_target_distance():
    run, counts, events, articles = sample_run_payload()
    articles[0]["analysis"]["mentioned_ticker_details"][0].update(
        {
            "company_name": "Apple Inc.",
            "polygon_reference": {"type": "CS", "market": "stocks", "locale": "us"},
            "asset_type": "stock",
        }
    )

    html = build_run_html_report(
        run,
        counts,
        events,
        articles,
        market_data_by_ticker={"AAPL": {"last_close": 200.0}},
    )

    text = _plain_text(html)
    assert "Last close: USD 200.00" in text
    assert "Upside/downside: +25.0%" in text


def test_build_run_html_report_normalizes_source_targets_to_polygon_last_close():
    run, counts, events, articles = sample_run_payload()
    articles[0]["analysis"]["mentioned_ticker_details"][0].update(
        {
            "company_name": "Credo Technology",
            "polygon_reference": {"type": "CS", "market": "stocks", "locale": "us"},
            "asset_type": "stock",
        }
    )

    html = build_run_html_report(
        run,
        counts,
        events,
        articles,
        market_data_by_ticker={"AAPL": {"last_close": 250.0}},
        rating_data_by_ticker={
            "AAPL": [
                {
                    "ticker": "AAPL",
                    "provider": "seeking_alpha",
                    "rating_type": "price_target",
                    "rating": "Wall Street price target",
                    "score": None,
                    "price_target": 269.81,
                    "currency": "USD",
                    "source_reported_upside_pct": 13.37,
                    "implied_last_close_from_reported_upside": 237.99,
                },
                {
                    "ticker": "AAPL",
                    "provider": "zacks",
                    "rating_type": "price_target",
                    "rating": "Zacks price target",
                    "score": None,
                    "price_target": 276.85,
                    "currency": "USD",
                    "source_reported_upside_pct": 3.29,
                    "source_last_close": 268.03,
                },
            ],
        },
    )

    text = _plain_text(html)
    assert "Last close: USD 250.00" in text
    assert "SA target" in html
    assert "USD 269.81 (Polygon +7.9%; source +13.37% vs implied close USD 237.99)" in html
    assert "Zacks target: USD 276.85 (Polygon +10.7%; source +3.29% vs source close USD 268.03)" in text


def test_build_run_html_report_marks_rating_targets_that_need_polygon_close():
    run, counts, events, articles = sample_run_payload()

    html = build_run_html_report(
        run,
        counts,
        events,
        articles,
        market_data_by_ticker={},
        rating_data_by_ticker={
            "AAPL": [
                {
                    "ticker": "AAPL",
                    "provider": "seeking_alpha",
                    "rating_type": "price_target",
                    "rating": "Wall Street price target",
                    "score": None,
                    "price_target": 269.81,
                    "currency": "USD",
                    "source_reported_upside_pct": 13.37,
                },
            ],
        },
    )

    assert "USD 269.81 (Polygon needs close; source +13.37%)" in html


def test_build_run_html_report_surfaces_blocked_and_low_quality_content():
    run, counts, events, articles = sample_run_payload()
    counts = {"gmail_messages": 3, "article_links": 3}
    articles.append(
        {
            "subject": "Blocked SA article",
            "source_key": "seeking_alpha",
            "normalized_url": "https://seekingalpha.com/article/blocked",
            "content": {
                "fetch_status": "blocked",
                "title": "Access to this page has been denied",
                "text_char_count": 0,
                "failure_reason": "Source blocked article extraction with a human verification page",
            },
            "analysis": None,
        }
    )

    html = build_run_html_report(run, counts, events, articles)

    assert "usable article" in html.lower()
    assert "Blocked/source-check" in html
    assert "2 / 3" in html
    assert "high-quality data set" not in html


def test_export_run_pdf_endpoint_uses_persisted_polygon_snapshot_without_refetch(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("APP_DASHBOARD_PASSWORD", "change-me")
    monkeypatch.setenv("POLYGON_API_KEY", "polygon-key")
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_repo = RunRepository(db_path)
    gmail_repo = GmailDiscoveryRepository(db_path)
    watchlist_repo = WatchlistRepository(db_path)
    upload_id = watchlist_repo.create_upload("portfolio.csv", ["Symbol"], [{"Symbol": "AAPL"}], 1)
    watchlist_repo.replace_items(
        upload_id,
        [
            {
                "ticker": "AAPL",
                "normalized_ticker": "AAPL",
                "company_name": "Apple Inc.",
                "sector": None,
                "priority": None,
                "notes": None,
                "polygon_reference": None,
            }
        ],
    )
    run_id = run_repo.create_run("gpt-5.4", "gpt-5.4-mini")
    message_id = gmail_repo.save_message(
        run_id=run_id,
        gmail_message_id="msg-1",
        thread_id="thread-1",
        sender="alerts@seekingalpha.com",
        subject="Apple gets a new target",
        labels=["UNREAD"],
        source_key="seeking_alpha",
        processing_status="analyzed",
    )
    link_id = gmail_repo.save_article_link(
        gmail_message_row_id=message_id,
        source_key="seeking_alpha",
        raw_url="https://seekingalpha.com/article/1",
        normalized_url="https://seekingalpha.com/article/1",
        detection_method="headline_anchor",
        detection_confidence=0.91,
        heuristic_notes=None,
    )
    gmail_repo.save_article_content(
        article_link_id=link_id,
        fetch_status="fetched",
        final_url="https://seekingalpha.com/article/1",
        http_status=200,
        title="Apple gets a new target",
        extracted_text="Body",
        failure_reason=None,
    )
    gmail_repo.save_article_analysis(
        article_link_id=link_id,
        provider="openai",
        model="gpt-5.4-mini",
        summary="Apple demand improved.",
        stance="buy_watch",
        confidence=0.82,
        supporting_evidence=["Raised demand view", "Margin expansion"],
        mentioned_tickers=["AAPL"],
        raw_response={
            "sentiment": "bullish",
            "recommendation": "buy",
            "price_targets": [{"ticker": "AAPL", "target_price": 250, "currency": "USD"}],
            "actionable_data": [{"ticker": "AAPL", "recommendation": "buy"}],
        },
    )
    run_repo.save_ticker_enrichment(
        run_id=run_id,
        ticker="AAPL",
        provider="seeking_alpha",
        data_type="quant",
        data={
            "ticker": "AAPL",
            "provider": "seeking_alpha",
            "rating_type": "quant",
            "rating": "Strong Buy",
            "score": 4.82,
            "price_target": None,
            "currency": "USD",
            "source_text": "SA Quant Rating Strong Buy 4.82",
        },
    )
    run_repo.save_ticker_enrichment(
        run_id=run_id,
        ticker="AAPL",
        provider="polygon",
        data_type="previous_close",
        data={"ticker": "AAPL", "last_close": 205.5, "source": "polygon_previous_close"},
    )

    class FakePolygonClient:
        calls = []

        def __init__(self, api_key):
            assert api_key == "polygon-key"

        def previous_close(self, ticker):
            self.calls.append(ticker)
            return {
                "ticker": ticker,
                "last_close": 205.5,
                "source": "polygon_previous_close",
            }

    market_payloads = []

    def fake_pdf_report(
        run,
        counts,
        events,
        articles,
        market_data_by_ticker=None,
        rating_data_by_ticker=None,
        pdf_renderer=None,
    ):
        assert run["id"] == run_id
        assert articles[0]["analysis"]["mentioned_ticker_details"] == [
            {
                "ticker": "AAPL",
                "in_portfolio": True,
                "company_name": "Apple Inc.",
                "sector": None,
                "priority": None,
                "notes": None,
                "polygon_reference": {},
                "asset_type": None,
            }
        ]
        assert rating_data_by_ticker == {
            "AAPL": [
                {
                    "ticker": "AAPL",
                    "provider": "seeking_alpha",
                    "rating_type": "quant",
                    "rating": "Strong Buy",
                    "score": 4.82,
                    "price_target": None,
                    "currency": "USD",
                    "source_text": "SA Quant Rating Strong Buy 4.82",
                }
            ]
        }
        market_payloads.append(market_data_by_ticker)
        return b"%PDF-1.4 fake"

    monkeypatch.setattr("email_article_analyzer.api.runs.build_run_pdf_report", fake_pdf_report)
    app = create_app(database_path=db_path)
    client = TestClient(app)

    response = client.get(f"/api/runs/{run_id}/report.pdf")
    second_response = client.get(f"/api/runs/{run_id}/report.pdf")

    assert response.status_code == 200
    assert second_response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["content-disposition"] == (
        f'attachment; filename="email-article-run-{run_id}-report.pdf"'
    )
    assert response.content == b"%PDF-1.4 fake"
    assert second_response.content == b"%PDF-1.4 fake"
    assert FakePolygonClient.calls == []
    assert market_payloads == [
        {"AAPL": {"ticker": "AAPL", "last_close": 205.5, "source": "polygon_previous_close"}},
        {"AAPL": {"ticker": "AAPL", "last_close": 205.5, "source": "polygon_previous_close"}},
    ]
    assert run_repo.list_ticker_enrichments(run_id)[0]["data"] == {
        "ticker": "AAPL",
        "last_close": 205.5,
        "source": "polygon_previous_close",
    }
