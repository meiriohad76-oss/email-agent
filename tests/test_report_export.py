from fastapi.testclient import TestClient

from email_article_analyzer.db import initialize_database
from email_article_analyzer.main import create_app
from email_article_analyzer.report_export import build_run_markdown_report
from email_article_analyzer.repositories import (
    GmailDiscoveryRepository,
    RunRepository,
    WatchlistRepository,
)


def test_build_run_markdown_report_separates_portfolio_and_non_portfolio_articles():
    report = build_run_markdown_report(
        run={
            "id": 7,
            "status": "completed",
            "extraction_model": "gpt-5.4",
            "summary_model": "gpt-5.4-mini",
            "started_at": "2026-06-21 08:00:00",
            "completed_at": "2026-06-21 08:05:00",
        },
        counts={"gmail_messages": 2, "article_links": 2},
        events=[
            {
                "event_type": "article_analysis_failed",
                "stage": "analysis",
                "severity": "error",
                "message": "One article could not be analyzed.",
            }
        ],
        articles=[
            {
                "subject": "Apple gets a new target",
                "source_key": "seeking_alpha",
                "normalized_url": "https://seekingalpha.com/article/1",
                "detection_confidence": 0.92,
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
                    "supporting_evidence": ["Services margin expanded", "Raised iPhone demand view"],
                    "mentioned_ticker_details": [{"ticker": "AAPL", "in_portfolio": True}],
                    "mentioned_tickers": ["AAPL"],
                    "price_targets": [
                        {
                            "ticker": "AAPL",
                            "target_price": 250,
                            "currency": "USD",
                            "timeframe": "12 months",
                        }
                    ],
                    "actionable_data": [
                        {
                            "ticker": "AAPL",
                            "recommendation": "buy",
                            "sentiment": "bullish",
                            "timeframe": "12 months",
                            "catalysts": ["Services margin expansion"],
                            "risks": ["China demand"],
                            "financial_details": ["Price target USD 250"],
                        }
                    ],
                },
            },
            {
                "subject": "Small cap setup",
                "source_key": "zacks",
                "normalized_url": "https://www.zacks.com/article/2",
                "detection_confidence": 0.65,
                "content": {"fetch_status": "email_fallback", "title": None, "text_char_count": 900},
                "analysis": {
                    "summary": "A non-portfolio stock is improving.",
                    "stance": "watch",
                    "sentiment": "positive",
                    "recommendation": "hold",
                    "confidence": 0.62,
                    "supporting_evidence": ["Estimate revisions improved"],
                    "mentioned_ticker_details": [{"ticker": "XYZ", "in_portfolio": False}],
                    "mentioned_tickers": ["XYZ"],
                    "price_targets": [],
                    "actionable_data": [],
                },
            },
        ],
    )

    assert "# Daily Stock Article Intelligence - Run #7" in report
    assert "## Executive Summary" in report
    assert "2 article links" in report
    assert "## Portfolio Impact" in report
    assert "AAPL (portfolio)" in report
    assert "Recommendation: buy" in report
    assert "Sentiment: bullish" in report
    assert "AAPL USD 250 12 months" in report
    assert "Services margin expanded" in report
    assert "## Non-Portfolio Opportunities" in report
    assert "XYZ (not portfolio)" in report
    assert "## Low-Quality Or Failed Items" in report
    assert "65% link confidence" in report
    assert "## Caveats And Assumptions" in report


def test_export_run_report_endpoint_returns_downloadable_markdown(tmp_path):
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
    app = create_app(database_path=db_path)
    client = TestClient(app)

    response = client.get(f"/api/runs/{run_id}/report.md")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.headers["content-disposition"] == (
        f'attachment; filename="email-article-run-{run_id}-report.md"'
    )
    assert f"# Daily Stock Article Intelligence - Run #{run_id}" in response.text
    assert "AAPL (portfolio)" in response.text
    assert "Recommendation: buy" in response.text


def test_export_run_report_endpoint_returns_not_found_for_missing_run(tmp_path):
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    response = client.get("/api/runs/404/report.md")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"
