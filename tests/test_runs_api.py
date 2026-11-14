from pathlib import Path

from fastapi.testclient import TestClient

from email_article_analyzer.db import initialize_database
from email_article_analyzer.application import create_app
from email_article_analyzer.model_defaults import DEFAULT_EXTRACTION_MODEL
from email_article_analyzer.model_defaults import DEFAULT_SUMMARY_MODEL
from email_article_analyzer.repositories import GmailDiscoveryRepository, RunRepository, WatchlistRepository
from email_article_analyzer.run_orchestration import RunResult


class FakeRunOrchestrator:
    def __init__(self):
        self.calls = []

    def start_discovery_run(self, extraction_model, summary_model):
        self.calls.append((extraction_model, summary_model))
        return RunResult(
            run_id=123,
            status="completed",
            candidate_count=2,
            needed_source_logins=["seeking_alpha", "zacks"],
        )


class FailingRunOrchestrator:
    def start_discovery_run(self, extraction_model, summary_model):
        raise RuntimeError("Gmail API TLS verification failed")


class FakeRunDeleteGmailProvider:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.calls = []
        self.mark_read_calls = []
        self.add_label_calls = []
        self.remove_label_calls = []

    def reset_processing_labels_for_messages(self, message_ids, label_names, mark_unread):
        self.calls.append(
            {
                "message_ids": message_ids,
                "label_names": label_names,
                "mark_unread": mark_unread,
            }
        )
        if self.should_fail:
            raise RuntimeError("Gmail reset failed")
        return len(message_ids)

    def mark_read(self, message_id):
        if self.should_fail:
            raise RuntimeError("Gmail mark failed")
        self.mark_read_calls.append(message_id)

    def add_label(self, message_id, label):
        if self.should_fail:
            raise RuntimeError("Gmail mark failed")
        self.add_label_calls.append((message_id, label))

    def remove_label(self, message_id, label):
        if self.should_fail:
            raise RuntimeError("Gmail mark failed")
        self.remove_label_calls.append((message_id, label))


class PartiallyFailingRunDeleteGmailProvider(FakeRunDeleteGmailProvider):
    def reset_processing_labels_for_messages(self, message_ids, label_names, mark_unread):
        from email_article_analyzer.providers.gmail_api import GmailLabelResetError

        self.calls.append(
            {
                "message_ids": message_ids,
                "label_names": label_names,
                "mark_unread": mark_unread,
            }
        )
        raise GmailLabelResetError(
            "Gmail reset failed after 1 message(s): simulated",
            reset_count=1,
            total_count=len(message_ids),
        )


class FakeAtomicGmailMarkProvider(FakeRunDeleteGmailProvider):
    def __init__(self, should_fail=False):
        super().__init__(should_fail=should_fail)
        self.mark_analyzed_calls = []
        self.mark_failed_calls = []

    def mark_analyzed(self, message_id, analyzed_label, failed_label):
        if self.should_fail:
            raise RuntimeError("Gmail mark failed")
        self.mark_analyzed_calls.append((message_id, analyzed_label, failed_label))

    def mark_failed(self, message_id, failed_label):
        if self.should_fail:
            raise RuntimeError("Gmail mark failed")
        self.mark_failed_calls.append((message_id, failed_label))


class FakeRatingEnricher:
    def __init__(self):
        self.calls = []

    def enrich_ticker(self, run_id, ticker):
        self.calls.append({"run_id": run_id, "ticker": ticker})
        return {"attempted": 4, "saved": 2, "failed": 0}


class FakeRunOrchestratorWithEnricher:
    def __init__(self, rating_enricher):
        self.rating_enricher = rating_enricher


def configure_ready_essentials(tmp_path, monkeypatch):
    credentials_path = tmp_path / "gmail_credentials.json"
    token_path = tmp_path / "gmail_token.json"
    credentials_path.write_text("{}", encoding="utf-8")
    token_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("GMAIL_CREDENTIALS_PATH", str(credentials_path))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(token_path))


def test_create_run_endpoint_starts_discovery_run(tmp_path, monkeypatch):
    configure_ready_essentials(tmp_path, monkeypatch)
    fake_orchestrator = FakeRunOrchestrator()
    app = create_app(
        database_path=str(tmp_path / "app.db"),
        run_orchestrator=fake_orchestrator,
    )
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={"extraction_model": "gpt-extract", "summary_model": "gpt-summary"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "run_id": 123,
        "status": "completed",
        "candidate_count": 2,
        "needed_source_logins": ["seeking_alpha", "zacks"],
        "alerts": [],
    }
    assert fake_orchestrator.calls == [("gpt-extract", "gpt-summary")]


def test_create_run_endpoint_rejects_when_required_chrome_bridge_is_disconnected(
    tmp_path,
    monkeypatch,
):
    configure_ready_essentials(tmp_path, monkeypatch)
    fake_orchestrator = FakeRunOrchestrator()
    app = create_app(
        database_path=str(tmp_path / "app.db"),
        run_orchestrator=fake_orchestrator,
    )
    app.state.browser_bridge_required_for_runs = True
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={"extraction_model": "gpt-extract", "summary_model": "gpt-summary"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "message": "Chrome bridge is not connected",
        "next": "Reload or enable the Email Article Analyzer Bridge extension, then wait for the dashboard to show Chrome bridge connected.",
    }
    assert fake_orchestrator.calls == []


def test_create_run_endpoint_rejects_when_another_run_is_active(tmp_path, monkeypatch):
    configure_ready_essentials(tmp_path, monkeypatch)
    fake_orchestrator = FakeRunOrchestrator()
    app = create_app(
        database_path=str(tmp_path / "app.db"),
        run_orchestrator=fake_orchestrator,
    )
    assert app.state.run_control.begin_run() is True
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={"extraction_model": "gpt-extract", "summary_model": "gpt-summary"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["message"] == "Another discovery run is already active"
    assert fake_orchestrator.calls == []
    app.state.run_control.end_run()


def test_create_run_endpoint_normalizes_blank_models_to_defaults(tmp_path, monkeypatch):
    configure_ready_essentials(tmp_path, monkeypatch)
    fake_orchestrator = FakeRunOrchestrator()
    app = create_app(
        database_path=str(tmp_path / "app.db"),
        run_orchestrator=fake_orchestrator,
    )
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={"extraction_model": "  ", "summary_model": None},
    )

    assert response.status_code == 200
    assert fake_orchestrator.calls == [
        (DEFAULT_EXTRACTION_MODEL, DEFAULT_SUMMARY_MODEL)
    ]


def test_create_run_endpoint_rejects_object_model_values(tmp_path, monkeypatch):
    configure_ready_essentials(tmp_path, monkeypatch)
    fake_orchestrator = FakeRunOrchestrator()
    app = create_app(
        database_path=str(tmp_path / "app.db"),
        run_orchestrator=fake_orchestrator,
    )
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={"extraction_model": {"name": "gpt"}, "summary_model": "gpt-summary"},
    )

    assert response.status_code == 422
    assert "model name must be a string" in response.text
    assert fake_orchestrator.calls == []


def test_create_run_endpoint_rejects_when_essential_providers_are_not_ready(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GMAIL_CREDENTIALS_PATH", str(tmp_path / "missing_credentials.json"))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "missing_token.json"))
    fake_orchestrator = FakeRunOrchestrator()
    app = create_app(
        database_path=str(tmp_path / "app.db"),
        run_orchestrator=fake_orchestrator,
    )
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={"extraction_model": "gpt-extract", "summary_model": "gpt-summary"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["missing_essential_providers"] == ["openai", "gmail"]
    assert fake_orchestrator.calls == []


def test_create_run_endpoint_returns_bad_gateway_when_orchestrator_fails(tmp_path, monkeypatch):
    configure_ready_essentials(tmp_path, monkeypatch)
    app = create_app(
        database_path=str(tmp_path / "app.db"),
        run_orchestrator=FailingRunOrchestrator(),
    )
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={"extraction_model": "gpt-extract", "summary_model": "gpt-summary"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "message": "Discovery run failed",
        "error": "Gmail API TLS verification failed",
    }


def test_stop_current_run_endpoint_requests_cooperative_stop(tmp_path):
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    response = client.post("/api/runs/stop-current")

    assert response.status_code == 200
    assert response.json() == {
        "status": "stop_requested",
        "message": "Current run will stop after the active article finishes.",
    }
    assert app.state.run_control.is_stop_requested() is True


def test_force_stop_run_endpoint_marks_running_run_stopped(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_repo = RunRepository(db_path)
    run_id = run_repo.create_run("gpt-extract", "gpt-summary")
    app = create_app(database_path=db_path)
    client = TestClient(app)

    response = client.post(f"/api/runs/{run_id}/force-stop")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": run_id,
        "status": "stopped",
        "message": "Run marked stopped.",
    }
    run = run_repo.get_run(run_id)
    assert run["status"] == "stopped"
    assert run["completed_at"] is not None
    assert run_repo.list_events(run_id)[0]["event_type"] == "run_force_stopped"


def test_force_stop_run_endpoint_does_not_change_completed_run(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_repo = RunRepository(db_path)
    run_id = run_repo.create_run("gpt-extract", "gpt-summary")
    run_repo.complete_run(run_id, status="completed")
    app = create_app(database_path=db_path)
    client = TestClient(app)

    response = client.post(f"/api/runs/{run_id}/force-stop")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": run_id,
        "status": "completed",
        "message": "Run is not running.",
    }


def test_get_run_endpoint_returns_status_counts_and_events(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_repo = RunRepository(db_path)
    gmail_repo = GmailDiscoveryRepository(db_path)
    run_id = run_repo.create_run("gpt-extract", "gpt-summary")
    run_repo.add_event(run_id, "run_started", "startup", "Run started")
    run_repo.save_ticker_enrichment(
        run_id=run_id,
        ticker="NVDA",
        provider="seeking_alpha",
        data_type="quant",
        data={
            "ticker": "NVDA",
            "provider": "seeking_alpha",
            "rating_type": "quant",
            "rating": "Strong Buy",
            "score": 4.82,
            "price_target": None,
            "currency": "USD",
            "source_text": "SA Quant Rating Strong Buy 4.82",
        },
        source_url="https://seekingalpha.com/symbol/NVDA/ratings/quant-ratings",
    )
    run_repo.save_ticker_enrichment(
        run_id=run_id,
        ticker="NVDA",
        provider="zacks",
        data_type="quote",
        data={},
        source_url="https://www.zacks.com/stock/quote/NVDA",
        status="failed",
        failure_reason="No visible article text extracted",
    )
    message_row_id = gmail_repo.save_message(
        run_id=run_id,
        gmail_message_id="msg-1",
        thread_id="thread-1",
        sender="alerts@seekingalpha.com",
        subject="Story",
        labels=["UNREAD"],
        source_key="seeking_alpha",
        processing_status="discovered",
    )
    link_id = gmail_repo.save_article_link(
        gmail_message_row_id=message_row_id,
        source_key="seeking_alpha",
        raw_url="https://seekingalpha.com/article/1",
        normalized_url="https://seekingalpha.com/article/1",
        detection_method="headline_anchor",
        detection_confidence=0.9,
        heuristic_notes=None,
    )
    gmail_repo.save_article_content(
        article_link_id=link_id,
        fetch_status="fetched",
        final_url="https://seekingalpha.com/article/1",
        http_status=200,
        title="Story title",
        extracted_text="Article body text.",
        failure_reason=None,
    )
    gmail_repo.save_article_analysis(
        article_link_id=link_id,
        provider="openai",
        model="gpt-summary",
        summary="Margins improved.",
        stance="buy_watch",
        confidence=0.82,
        supporting_evidence=["Raised guide", "Margin expansion"],
        mentioned_tickers=["NVDA"],
        raw_response={"id": "resp-1"},
    )
    app = create_app(database_path=db_path)
    client = TestClient(app)

    response = client.get(f"/api/runs/{run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["id"] == run_id
    assert payload["run"]["status"] == "running"
    assert payload["counts"] == {"gmail_messages": 1, "article_links": 1}
    assert payload["alerts"] == []
    assert payload["events"][0]["event_type"] == "run_started"
    assert payload["ticker_enrichments"] == [
        {
            "id": payload["ticker_enrichments"][0]["id"],
            "run_id": run_id,
            "ticker": "NVDA",
            "provider": "seeking_alpha",
            "data_type": "quant",
            "data": {
                "ticker": "NVDA",
                "provider": "seeking_alpha",
                "rating_type": "quant",
                "rating": "Strong Buy",
                "score": 4.82,
                "price_target": None,
                "currency": "USD",
                "source_text": "SA Quant Rating Strong Buy 4.82",
            },
            "source_url": "https://seekingalpha.com/symbol/NVDA/ratings/quant-ratings",
            "status": "ready",
            "failure_reason": None,
            "created_at": payload["ticker_enrichments"][0]["created_at"],
            "updated_at": payload["ticker_enrichments"][0]["updated_at"],
        },
        {
            "id": payload["ticker_enrichments"][1]["id"],
            "run_id": run_id,
            "ticker": "NVDA",
            "provider": "zacks",
            "data_type": "quote",
            "data": {},
            "source_url": "https://www.zacks.com/stock/quote/NVDA",
            "status": "failed",
            "failure_reason": "No visible article text extracted",
            "created_at": payload["ticker_enrichments"][1]["created_at"],
            "updated_at": payload["ticker_enrichments"][1]["updated_at"],
        },
    ]
    assert payload["articles"] == [
        {
            "article_link_id": 1,
            "gmail_message_id": "msg-1",
            "sender": "alerts@seekingalpha.com",
            "subject": "Story",
            "message_status": "discovered",
            "source_key": "seeking_alpha",
            "normalized_url": "https://seekingalpha.com/article/1",
            "detection_method": "headline_anchor",
            "detection_confidence": 0.9,
            "content": {
                "fetch_status": "fetched",
                "title": "Story title",
                "text_char_count": len("Article body text."),
                "failure_reason": None,
            },
            "analysis": {
                "provider": "openai",
                "model": "gpt-summary",
                "summary": "Margins improved.",
                "stance": "buy_watch",
                "sentiment": "unclear",
                "recommendation": "unclear",
                "confidence": 0.82,
                "supporting_evidence": ["Raised guide", "Margin expansion"],
                "mentioned_tickers": ["NVDA"],
                "mentioned_ticker_details": [
                    {"ticker": "NVDA", "in_portfolio": False},
                ],
                "price_targets": [],
                "rating_snapshots": [],
                "actionable_data": [],
                "actionable_signals": [],
            },
        }
    ]


def test_get_run_endpoint_enriches_portfolio_tickers_with_watchlist_metadata(tmp_path):
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
                "sector": "Technology",
                "priority": "core",
                "notes": "Large position",
                "polygon_reference": '{"name":"Apple Inc.","type":"CS","market":"stocks","locale":"us"}',
            }
        ],
    )
    run_id = run_repo.create_run("gpt-extract", "gpt-summary")
    message_row_id = gmail_repo.save_message(
        run_id=run_id,
        gmail_message_id="msg-action",
        thread_id="thread-action",
        sender="alerts@seekingalpha.com",
        subject="Apple target raised",
        labels=["UNREAD"],
        source_key="seeking_alpha",
        processing_status="analyzed",
    )
    link_id = gmail_repo.save_article_link(
        gmail_message_row_id=message_row_id,
        source_key="seeking_alpha",
        raw_url="https://seekingalpha.com/article/aapl",
        normalized_url="https://seekingalpha.com/article/aapl",
        detection_method="headline_anchor",
        detection_confidence=0.91,
        heuristic_notes=None,
    )
    gmail_repo.save_article_content(
        article_link_id=link_id,
        fetch_status="fetched",
        final_url="https://seekingalpha.com/article/aapl",
        http_status=200,
        title="Apple target raised",
        extracted_text="Body",
        failure_reason=None,
    )
    gmail_repo.save_article_analysis(
        article_link_id=link_id,
        provider="openai",
        model="gpt-summary",
        summary="Apple margin outlook improved.",
        stance="buy_watch",
        confidence=0.86,
        supporting_evidence=["Target raised", "Services margin expanded"],
        mentioned_tickers=["AAPL"],
        raw_response={
            "sentiment": "bullish",
            "recommendation": "buy",
            "price_targets": [{"ticker": "AAPL", "target_price": 250, "currency": "USD"}],
            "actionable_data": [
                {
                    "ticker": "AAPL",
                    "recommendation": "buy",
                    "sentiment": "bullish",
                    "catalysts": ["Services margin expansion"],
                    "risks": ["China demand"],
                    "financial_details": ["Target raised to $250"],
                    "evidence": ["Target raised", "Services margin expanded"],
                }
            ],
            "actionable_signals": [
                {
                    "ticker": "AAPL",
                    "signal_type": "valuation",
                    "signal": "Price target raised",
                    "value": "$250",
                    "direction": "positive",
                    "timeframe": "12 months",
                    "source_text": "Target raised",
                }
            ],
        },
    )
    app = create_app(database_path=db_path)
    client = TestClient(app)

    response = client.get(f"/api/runs/{run_id}")

    assert response.status_code == 200
    ticker_detail = response.json()["articles"][0]["analysis"]["mentioned_ticker_details"][0]
    assert ticker_detail == {
        "ticker": "AAPL",
        "in_portfolio": True,
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


def test_retry_run_enrichments_endpoint_refetches_portfolio_ticker_snapshots(tmp_path):
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
    run_id = run_repo.create_run("gpt-extract", "gpt-summary")
    message_row_id = gmail_repo.save_message(
        run_id=run_id,
        gmail_message_id="msg-aapl",
        thread_id="thread-aapl",
        sender="alerts@seekingalpha.com",
        subject="Apple target raised",
        labels=["UNREAD"],
        source_key="seeking_alpha",
        processing_status="analyzed",
    )
    link_id = gmail_repo.save_article_link(
        gmail_message_row_id=message_row_id,
        source_key="seeking_alpha",
        raw_url="https://seekingalpha.com/article/aapl",
        normalized_url="https://seekingalpha.com/article/aapl",
        detection_method="headline_anchor",
        detection_confidence=0.91,
        heuristic_notes=None,
    )
    gmail_repo.save_article_analysis(
        article_link_id=link_id,
        provider="openai",
        model="gpt-summary",
        summary="Apple margin outlook improved.",
        stance="buy_watch",
        confidence=0.86,
        supporting_evidence=["Target raised", "Services margin expanded"],
        mentioned_tickers=["AAPL"],
        raw_response={
            "sentiment": "bullish",
            "recommendation": "buy",
            "actionable_data": [{"ticker": "AAPL", "recommendation": "buy"}],
        },
    )
    rating_enricher = FakeRatingEnricher()
    app = create_app(
        database_path=db_path,
        run_orchestrator=FakeRunOrchestratorWithEnricher(rating_enricher),
    )
    client = TestClient(app)

    response = client.post(f"/api/runs/{run_id}/retry-enrichments?force=true")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["run_id"] == run_id
    assert payload["results"] == [{"ticker": "AAPL", "attempted": 4, "saved": 2, "failed": 0}]
    assert payload["ticker_enrichments"] == []
    assert rating_enricher.calls == [{"run_id": run_id, "ticker": "AAPL"}]
    events = run_repo.list_events(run_id)
    assert events[-1]["event_type"] == "ticker_rating_enriched"
    assert events[-1]["entity_id"] == "AAPL"


def test_retry_run_enrichments_endpoint_uses_actionable_portfolio_tickers(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_repo = RunRepository(db_path)
    gmail_repo = GmailDiscoveryRepository(db_path)
    watchlist_repo = WatchlistRepository(db_path)
    upload_id = watchlist_repo.create_upload("portfolio.csv", ["Symbol"], [{"Symbol": "NVDA"}], 1)
    watchlist_repo.replace_items(
        upload_id,
        [
            {
                "ticker": "NVDA",
                "normalized_ticker": "NVDA",
                "company_name": "Nvidia",
                "sector": None,
                "priority": None,
                "notes": None,
                "polygon_reference": None,
            }
        ],
    )
    run_id = run_repo.create_run("gpt-extract", "gpt-summary")
    message_row_id = gmail_repo.save_message(
        run_id=run_id,
        gmail_message_id="msg-nvda",
        thread_id="thread-nvda",
        sender="alerts@seekingalpha.com",
        subject="Nvidia guide raised",
        labels=["UNREAD"],
        source_key="seeking_alpha",
        processing_status="analyzed",
    )
    link_id = gmail_repo.save_article_link(
        gmail_message_row_id=message_row_id,
        source_key="seeking_alpha",
        raw_url="https://seekingalpha.com/article/nvda",
        normalized_url="https://seekingalpha.com/article/nvda",
        detection_method="headline_anchor",
        detection_confidence=0.91,
        heuristic_notes=None,
    )
    gmail_repo.save_article_analysis(
        article_link_id=link_id,
        provider="openai",
        model="gpt-summary",
        summary="Nvidia guide improved.",
        stance="buy_watch",
        confidence=0.86,
        supporting_evidence=["Guide raised"],
        mentioned_tickers=[],
        raw_response={
            "sentiment": "bullish",
            "recommendation": "buy",
            "actionable_data": [{"ticker": "NVDA", "recommendation": "buy"}],
        },
    )
    rating_enricher = FakeRatingEnricher()
    app = create_app(
        database_path=db_path,
        run_orchestrator=FakeRunOrchestratorWithEnricher(rating_enricher),
    )
    client = TestClient(app)

    response = client.post(f"/api/runs/{run_id}/retry-enrichments?force=true")

    assert response.status_code == 200
    assert response.json()["results"] == [{"ticker": "NVDA", "attempted": 4, "saved": 2, "failed": 0}]
    assert rating_enricher.calls == [{"run_id": run_id, "ticker": "NVDA"}]


def test_retry_run_enrichments_endpoint_reuses_existing_ticker_data_by_default(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_repo = RunRepository(db_path)
    gmail_repo = GmailDiscoveryRepository(db_path)
    watchlist_repo = WatchlistRepository(db_path)
    upload_id = watchlist_repo.create_upload("portfolio.csv", ["Symbol"], [{"Symbol": "NVDA"}], 1)
    watchlist_repo.replace_items(
        upload_id,
        [
            {
                "ticker": "NVDA",
                "normalized_ticker": "NVDA",
                "company_name": "Nvidia",
                "sector": None,
                "priority": None,
                "notes": None,
                "polygon_reference": None,
            }
        ],
    )
    run_id = run_repo.create_run("gpt-extract", "gpt-summary")
    run_repo.save_ticker_enrichment(
        run_id=run_id,
        ticker="NVDA",
        provider="polygon",
        data_type="previous_close",
        data={"last_close": 123.45},
    )
    message_row_id = gmail_repo.save_message(
        run_id=run_id,
        gmail_message_id="msg-nvda",
        thread_id="thread-nvda",
        sender="alerts@seekingalpha.com",
        subject="Nvidia guide raised",
        labels=["UNREAD"],
        source_key="seeking_alpha",
        processing_status="analyzed",
    )
    link_id = gmail_repo.save_article_link(
        gmail_message_row_id=message_row_id,
        source_key="seeking_alpha",
        raw_url="https://seekingalpha.com/article/nvda",
        normalized_url="https://seekingalpha.com/article/nvda",
        detection_method="headline_anchor",
        detection_confidence=0.91,
        heuristic_notes=None,
    )
    gmail_repo.save_article_analysis(
        article_link_id=link_id,
        provider="openai",
        model="gpt-summary",
        summary="Nvidia guide improved.",
        stance="buy_watch",
        confidence=0.86,
        supporting_evidence=["Guide raised"],
        mentioned_tickers=[],
        raw_response={
            "sentiment": "bullish",
            "recommendation": "buy",
            "actionable_data": [{"ticker": "NVDA", "recommendation": "buy"}],
        },
    )
    rating_enricher = FakeRatingEnricher()
    app = create_app(
        database_path=db_path,
        run_orchestrator=FakeRunOrchestratorWithEnricher(rating_enricher),
    )
    client = TestClient(app)

    response = client.post(f"/api/runs/{run_id}/retry-enrichments")

    assert response.status_code == 200
    assert response.json()["results"] == [{"ticker": "NVDA", "attempted": 4, "saved": 2, "failed": 0}]
    assert rating_enricher.calls == [{"run_id": run_id, "ticker": "NVDA"}]


def test_retry_run_enrichments_endpoint_can_retry_one_requested_ticker(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_repo = RunRepository(db_path)
    gmail_repo = GmailDiscoveryRepository(db_path)
    watchlist_repo = WatchlistRepository(db_path)
    upload_id = watchlist_repo.create_upload(
        "portfolio.csv",
        ["Symbol"],
        [{"Symbol": "AEM"}, {"Symbol": "MSFT"}],
        2,
    )
    watchlist_repo.replace_items(
        upload_id,
        [
            {
                "ticker": ticker,
                "normalized_ticker": ticker,
                "company_name": None,
                "sector": None,
                "priority": None,
                "notes": None,
                "polygon_reference": None,
            }
            for ticker in ("AEM", "MSFT")
        ],
    )
    run_id = run_repo.create_run("gpt-extract", "gpt-summary")
    message_row_id = gmail_repo.save_message(
        run_id=run_id,
        gmail_message_id="msg-aem-msft",
        thread_id="thread-aem-msft",
        sender="alerts@seekingalpha.com",
        subject="AEM and MSFT update",
        labels=["UNREAD"],
        source_key="seeking_alpha",
        processing_status="analyzed",
    )
    link_id = gmail_repo.save_article_link(
        gmail_message_row_id=message_row_id,
        source_key="seeking_alpha",
        raw_url="https://seekingalpha.com/article/aem-msft",
        normalized_url="https://seekingalpha.com/article/aem-msft",
        detection_method="headline_anchor",
        detection_confidence=0.91,
        heuristic_notes=None,
    )
    gmail_repo.save_article_analysis(
        article_link_id=link_id,
        provider="openai",
        model="gpt-summary",
        summary="AEM and MSFT were discussed.",
        stance="hold",
        confidence=0.86,
        supporting_evidence=["AEM valuation", "MSFT AI demand"],
        mentioned_tickers=["AEM", "MSFT"],
        raw_response={"sentiment": "mixed", "recommendation": "hold"},
    )
    rating_enricher = FakeRatingEnricher()
    app = create_app(
        database_path=db_path,
        run_orchestrator=FakeRunOrchestratorWithEnricher(rating_enricher),
    )
    client = TestClient(app)

    response = client.post(f"/api/runs/{run_id}/retry-enrichments?ticker=AEM&force=true")

    assert response.status_code == 200
    assert response.json()["results"] == [{"ticker": "AEM", "attempted": 4, "saved": 2, "failed": 0}]
    assert rating_enricher.calls == [{"run_id": run_id, "ticker": "AEM"}]


def test_retry_run_enrichments_can_explicitly_process_unlisted_research_ticker(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_repo = RunRepository(db_path)
    run_id = run_repo.create_run("research-extract", "research-summary")
    rating_enricher = FakeRatingEnricher()
    app = create_app(
        database_path=db_path,
        run_orchestrator=FakeRunOrchestratorWithEnricher(rating_enricher),
    )
    client = TestClient(app)

    response = client.post(
        f"/api/runs/{run_id}/retry-enrichments",
        params={"ticker": "UBER", "force": "true", "allow_unlisted": "true"},
    )

    assert response.status_code == 200
    assert response.json()["results"] == [
        {"ticker": "UBER", "attempted": 4, "saved": 2, "failed": 0}
    ]
    assert rating_enricher.calls == [{"run_id": run_id, "ticker": "UBER"}]


def test_retry_run_enrichments_rejects_unbounded_unlisted_request(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_id = RunRepository(db_path).create_run("research-extract", "research-summary")
    app = create_app(
        database_path=db_path,
        run_orchestrator=FakeRunOrchestratorWithEnricher(FakeRatingEnricher()),
    )
    client = TestClient(app)

    response = client.post(
        f"/api/runs/{run_id}/retry-enrichments",
        params={"allow_unlisted": "true"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "allow_unlisted requires one explicit ticker and force=true"


def test_list_runs_endpoint_returns_recent_runs_with_counts(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_repo = RunRepository(db_path)
    gmail_repo = GmailDiscoveryRepository(db_path)
    older_run_id = run_repo.create_run("older-extract", "older-summary")
    run_repo.complete_run(older_run_id)
    newer_run_id = run_repo.create_run("newer-extract", "newer-summary")
    run_repo.complete_run(newer_run_id)
    message_row_id = gmail_repo.save_message(
        run_id=newer_run_id,
        gmail_message_id="msg-2",
        thread_id="thread-2",
        sender="alerts@zacks.com",
        subject="Newer Story",
        labels=["UNREAD"],
        source_key="zacks",
        processing_status="discovered",
    )
    gmail_repo.save_article_link(
        gmail_message_row_id=message_row_id,
        source_key="zacks",
        raw_url="https://www.zacks.com/article/2",
        normalized_url="https://www.zacks.com/article/2",
        detection_method="headline_anchor",
        detection_confidence=0.91,
        heuristic_notes=None,
    )
    app = create_app(database_path=db_path)
    client = TestClient(app)

    response = client.get("/api/runs")

    assert response.status_code == 200
    payload = response.json()
    assert [run["id"] for run in payload["runs"]] == [newer_run_id, older_run_id]
    assert payload["runs"][0]["status"] == "completed"
    assert payload["runs"][0]["counts"] == {"gmail_messages": 1, "article_links": 1}
    assert payload["runs"][0]["alerts"] == []
    assert payload["runs"][1]["counts"] == {"gmail_messages": 0, "article_links": 0}
    assert payload["runs"][1]["alerts"] == []


def test_list_runs_warns_when_history_is_empty_but_watchlist_exists(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    watchlist_repo = WatchlistRepository(db_path)
    upload_id = watchlist_repo.create_upload("portfolio.csv", ["Symbol"], [{"Symbol": "AAPL"}], 1)
    watchlist_repo.replace_items(
        upload_id,
        [
            {
                "ticker": "AAPL",
                "normalized_ticker": "AAPL",
                "company_name": "Apple",
                "sector": "Technology",
                "priority": None,
                "notes": None,
                "polygon_reference": None,
            }
        ],
    )
    app = create_app(database_path=db_path)
    client = TestClient(app)

    payload = client.get("/api/runs").json()

    assert payload["runs"] == []
    assert payload["alerts"][0]["type"] == "run_history_empty_with_watchlist"


def test_run_endpoints_surface_openai_quota_depleted_alert(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_repo = RunRepository(db_path)
    run_id = run_repo.create_run("gpt-extract", "gpt-summary")
    run_repo.add_event(
        run_id=run_id,
        event_type="candidate_processing_failed",
        stage="article_analysis",
        message="OpenAI quota exhausted; stopping run",
        severity="warning",
        details={
            "failure_reason": (
                "Error code: 429 - {'error': {'type': 'insufficient_quota', "
                "'code': 'insufficient_quota'}}"
            ),
        },
    )
    app = create_app(database_path=db_path)
    client = TestClient(app)

    detail_payload = client.get(f"/api/runs/{run_id}").json()
    list_payload = client.get("/api/runs").json()

    assert detail_payload["alerts"] == [
        {
            "type": "openai_quota_depleted",
            "severity": "error",
            "title": "OpenAI credits or quota appear depleted",
            "message": (
                "OpenAI returned an insufficient quota error. This usually means the API key's "
                "project has no available credits, billing is not active, or the project quota "
                "has been reached. Add credits or update billing in OpenAI, then start a new run."
            ),
            "next": "Check OpenAI billing/project limits and re-run after the API key has quota.",
        }
    ]
    assert list_payload["runs"][0]["alerts"] == detail_payload["alerts"]


def test_delete_run_endpoint_resets_gmail_flags_then_deletes_run_data(tmp_path, monkeypatch):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_repo = RunRepository(db_path)
    gmail_repo = GmailDiscoveryRepository(db_path)
    run_id = run_repo.create_run("gpt-extract", "gpt-summary")
    run_repo.complete_run(run_id)
    other_run_id = run_repo.create_run("other-extract", "other-summary")
    run_repo.complete_run(other_run_id)
    run_repo.add_event(run_id, "article_analyzed", "analysis", "Done")
    run_repo.add_event(other_run_id, "run_started", "startup", "Other")
    run_repo.save_ticker_enrichment(
        run_id=run_id,
        ticker="AAPL",
        provider="polygon",
        data_type="previous_close",
        data={"last_close": 205.5},
    )
    message_row_id = gmail_repo.save_message(
        run_id=run_id,
        gmail_message_id="msg-delete",
        thread_id="thread-delete",
        sender="alerts@seekingalpha.com",
        subject="Delete Story",
        labels=["UNREAD", "Analyzed"],
        source_key="seeking_alpha",
        processing_status="analyzed",
    )
    other_message_row_id = gmail_repo.save_message(
        run_id=other_run_id,
        gmail_message_id="msg-keep",
        thread_id="thread-keep",
        sender="alerts@zacks.com",
        subject="Keep Story",
        labels=["UNREAD"],
        source_key="zacks",
        processing_status="discovered",
    )
    link_id = gmail_repo.save_article_link(
        gmail_message_row_id=message_row_id,
        source_key="seeking_alpha",
        raw_url="https://seekingalpha.com/article/delete",
        normalized_url="https://seekingalpha.com/article/delete",
        detection_method="headline_anchor",
        detection_confidence=0.9,
        heuristic_notes=None,
    )
    gmail_repo.save_article_link(
        gmail_message_row_id=other_message_row_id,
        source_key="zacks",
        raw_url="https://www.zacks.com/article/keep",
        normalized_url="https://www.zacks.com/article/keep",
        detection_method="headline_anchor",
        detection_confidence=0.91,
        heuristic_notes=None,
    )
    gmail_repo.save_article_content(
        article_link_id=link_id,
        fetch_status="fetched",
        final_url="https://seekingalpha.com/article/delete",
        http_status=200,
        title="Delete Story",
        extracted_text="Body",
        failure_reason=None,
    )
    gmail_repo.save_article_analysis(
        article_link_id=link_id,
        provider="openai",
        model="gpt-summary",
        summary="Summary",
        stance="hold",
        confidence=0.8,
        supporting_evidence=["Evidence"],
        mentioned_tickers=["AAPL"],
    )
    fake_provider = FakeRunDeleteGmailProvider()
    monkeypatch.setattr(
        "email_article_analyzer.api.runs.create_gmail_provider",
        lambda config: fake_provider,
    )
    app = create_app(database_path=db_path)
    client = TestClient(app)

    response = client.delete(f"/api/runs/{run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "deleted"
    assert payload["run_id"] == run_id
    assert payload["gmail_reset_count"] == 1
    assert payload["database_backup_path"].endswith(".db")
    assert Path(payload["database_backup_path"]).exists()
    assert payload["deleted"]["runs"] == 1
    assert payload["deleted"]["ticker_enrichments"] == 1
    assert fake_provider.calls == [
        {
            "message_ids": ["msg-delete"],
            "label_names": ["Analyzed", "Analysis Failed"],
            "mark_unread": True,
        }
    ]
    assert client.get(f"/api/runs/{run_id}").status_code == 404
    assert client.get(f"/api/runs/{other_run_id}").status_code == 200


def test_delete_run_endpoint_keeps_db_data_when_gmail_reset_fails(tmp_path, monkeypatch):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_repo = RunRepository(db_path)
    gmail_repo = GmailDiscoveryRepository(db_path)
    run_id = run_repo.create_run("gpt-extract", "gpt-summary")
    run_repo.complete_run(run_id)
    gmail_repo.save_message(
        run_id=run_id,
        gmail_message_id="msg-1",
        thread_id="thread-1",
        sender="alerts@seekingalpha.com",
        subject="Story",
        labels=["Analyzed"],
        source_key="seeking_alpha",
        processing_status="analyzed",
    )
    monkeypatch.setattr(
        "email_article_analyzer.api.runs.create_gmail_provider",
        lambda config: FakeRunDeleteGmailProvider(should_fail=True),
    )
    app = create_app(database_path=db_path)
    client = TestClient(app)

    response = client.delete(f"/api/runs/{run_id}")

    assert response.status_code == 502
    assert response.json()["detail"]["message"] == (
        "Gmail flag reset failed; database was not changed"
    )
    assert client.get(f"/api/runs/{run_id}").status_code == 200


def test_delete_run_endpoint_reports_partial_gmail_reset_failure(tmp_path, monkeypatch):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_repo = RunRepository(db_path)
    gmail_repo = GmailDiscoveryRepository(db_path)
    run_id = run_repo.create_run("gpt-extract", "gpt-summary")
    run_repo.complete_run(run_id)
    for message_id in ("msg-1", "msg-2"):
        gmail_repo.save_message(
            run_id=run_id,
            gmail_message_id=message_id,
            thread_id=f"thread-{message_id}",
            sender="alerts@seekingalpha.com",
            subject="Story",
            labels=["Analyzed"],
            source_key="seeking_alpha",
            processing_status="analyzed",
        )
    monkeypatch.setattr(
        "email_article_analyzer.api.runs.create_gmail_provider",
        lambda config: PartiallyFailingRunDeleteGmailProvider(),
    )
    app = create_app(database_path=db_path)
    client = TestClient(app)

    response = client.delete(f"/api/runs/{run_id}")

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["message"] == (
        "Gmail flag reset partially failed; database was not changed, "
        "but some Gmail labels may already have been reset"
    )
    assert detail["gmail_reset_count"] == 1
    assert detail["gmail_reset_total"] == 2
    assert client.get(f"/api/runs/{run_id}").status_code == 200


def test_retry_gmail_marks_endpoint_repairs_pending_run_messages(tmp_path, monkeypatch):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_repo = RunRepository(db_path)
    gmail_repo = GmailDiscoveryRepository(db_path)
    run_id = run_repo.create_run("gpt-extract", "gpt-summary")
    analyzed_row_id = gmail_repo.save_message(
        run_id=run_id,
        gmail_message_id="msg-analyzed",
        thread_id="thread-1",
        sender="alerts@seekingalpha.com",
        subject="Story",
        labels=["UNREAD"],
        source_key="seeking_alpha",
        processing_status="analyzed_gmail_mark_pending",
    )
    failed_row_id = gmail_repo.save_message(
        run_id=run_id,
        gmail_message_id="msg-failed",
        thread_id="thread-2",
        sender="alerts@seekingalpha.com",
        subject="Failed",
        labels=["UNREAD"],
        source_key="seeking_alpha",
        processing_status="failed_gmail_mark_pending",
    )
    provider = FakeAtomicGmailMarkProvider()
    monkeypatch.setattr(
        "email_article_analyzer.api.runs.create_gmail_provider",
        lambda config: provider,
    )
    app = create_app(database_path=db_path)
    client = TestClient(app)

    response = client.post(f"/api/runs/{run_id}/retry-gmail-marks")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["retried"] == 2
    assert payload["repaired"] == 2
    assert payload["failed"] == 0
    assert provider.mark_analyzed_calls == [("msg-analyzed", "Analyzed", "Analysis Failed")]
    assert provider.mark_failed_calls == [("msg-failed", "Analysis Failed")]
    assert provider.mark_read_calls == []
    assert provider.add_label_calls == []
    assert provider.remove_label_calls == []
    assert GmailDiscoveryRepository(db_path).get_message(analyzed_row_id)["processing_status"] == "analyzed"
    assert GmailDiscoveryRepository(db_path).get_message(failed_row_id)["processing_status"] == "failed"


def test_retry_gmail_marks_endpoint_keeps_pending_status_on_failure(tmp_path, monkeypatch):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    run_repo = RunRepository(db_path)
    gmail_repo = GmailDiscoveryRepository(db_path)
    run_id = run_repo.create_run("gpt-extract", "gpt-summary")
    row_id = gmail_repo.save_message(
        run_id=run_id,
        gmail_message_id="msg-analyzed",
        thread_id="thread-1",
        sender="alerts@seekingalpha.com",
        subject="Story",
        labels=["UNREAD"],
        source_key="seeking_alpha",
        processing_status="analyzed_gmail_mark_pending",
    )
    monkeypatch.setattr(
        "email_article_analyzer.api.runs.create_gmail_provider",
        lambda config: FakeRunDeleteGmailProvider(should_fail=True),
    )
    app = create_app(database_path=db_path)
    client = TestClient(app)

    response = client.post(f"/api/runs/{run_id}/retry-gmail-marks")

    assert response.status_code == 200
    payload = response.json()
    assert payload["retried"] == 1
    assert payload["repaired"] == 0
    assert payload["failed"] == 1
    message = GmailDiscoveryRepository(db_path).get_message(row_id)
    assert message["processing_status"] == "analyzed_gmail_mark_pending"
    assert "Gmail mark failed" in message["failure_reason"]


def test_delete_run_endpoint_returns_not_found_for_missing_run(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "email_article_analyzer.api.runs.create_gmail_provider",
        lambda config: FakeRunDeleteGmailProvider(),
    )
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    response = client.delete("/api/runs/404")

    assert response.status_code == 404

