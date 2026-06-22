from fastapi.testclient import TestClient

from email_article_analyzer.db import initialize_database
from email_article_analyzer.main import create_app
from email_article_analyzer.report_pdf_export import build_run_html_report
from email_article_analyzer.repositories import GmailDiscoveryRepository, RunRepository, WatchlistRepository


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
                        "recommendation": "buy",
                        "catalysts": ["Services margin expansion"],
                        "risks": ["China demand"],
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
    assert "Executive summary" in html
    assert "statband" in html
    assert "Portfolio-linked articles" in html
    assert "Price targets need market context before acting" in html
    assert "Detailed article appendix" in html
    assert "AAPL" in html
    assert "Buy Watch" in html
    assert "Sell Watch" in html
    assert "target raised to $250" in html
    assert "{{" not in html
    assert "<sc-for" not in html


def test_export_run_pdf_endpoint_returns_pdf_download(tmp_path, monkeypatch):
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

    def fake_pdf_report(run, counts, events, articles, pdf_renderer=None):
        assert run["id"] == run_id
        assert articles[0]["analysis"]["mentioned_ticker_details"] == [
            {"ticker": "AAPL", "in_portfolio": True}
        ]
        return b"%PDF-1.4 fake"

    monkeypatch.setattr("email_article_analyzer.api.runs.build_run_pdf_report", fake_pdf_report)
    app = create_app(database_path=db_path)
    client = TestClient(app)

    response = client.get(f"/api/runs/{run_id}/report.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["content-disposition"] == (
        f'attachment; filename="email-article-run-{run_id}-report.pdf"'
    )
    assert response.content == b"%PDF-1.4 fake"
