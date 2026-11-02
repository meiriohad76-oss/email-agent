import csv
from types import SimpleNamespace
import time

from fastapi.testclient import TestClient

from email_article_analyzer.application import create_app
from email_article_analyzer.api.research import _apply_sector_cohort_ranks
from email_article_analyzer.api.research import _bulk_extraction_order
from email_article_analyzer.api.research import classify_source_issue
from email_article_analyzer.repositories import RunRepository


def _write_universe(path):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Ticker", "Company", "Sector", "Priority", "Notes"])
        writer.writeheader()
        writer.writerow({"Ticker": "AAA", "Company": "Alpha Corp", "Sector": "Energy", "Priority": "70", "Notes": "ADR"})
        writer.writerow({"Ticker": "BBB", "Company": "Beta Corp", "Sector": "Healthcare", "Priority": "60", "Notes": "Pending"})


def _seed_research_run(database_path):
    repository = RunRepository(str(database_path))
    run_id = repository.create_run("extract", "summary")
    repository.save_ticker_enrichment(
        run_id,
        "AAA",
        "seeking_alpha",
        "quant",
        {"provider": "seeking_alpha", "rating_type": "quant", "ticker": "AAA", "rating": "buy"},
        source_url="https://seekingalpha.com/symbol/AAA/ratings/quant-ratings",
    )
    repository.save_ticker_enrichment(
        run_id,
        "AAA",
        "zacks",
        "quote",
        {"provider": "zacks", "rating_type": "quote", "ticker": "AAA"},
        source_url="https://www.zacks.com/stock/quote/AAA",
        status="failed",
        failure_reason="Blocked page",
    )
    repository.complete_run(run_id)
    return run_id


def test_research_universe_merges_frozen_universe_and_run_records(tmp_path):
    database_path = tmp_path / "app.db"
    app = create_app(database_path=str(database_path))
    _write_universe(tmp_path / "research_universe_120.csv")
    run_id = _seed_research_run(database_path)
    client = TestClient(app)

    response = client.get(f"/api/research/universe?run_id={run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["universe_count"] == 2
    assert payload["summary"]["companies_with_records"] == 1
    assert payload["summary"]["failed_source_records"] == 1
    by_ticker = {item["ticker"]: item for item in payload["companies"]}
    assert by_ticker["AAA"]["research_status"] == "partial"
    assert by_ticker["AAA"]["failed_record_count"] == 1
    assert by_ticker["BBB"]["research_status"] == "pending"
    assert by_ticker["BBB"]["composite_score"] is None


def test_research_weights_can_be_customized_and_reset(tmp_path):
    database_path = tmp_path / "app.db"
    app = create_app(database_path=str(database_path))
    client = TestClient(app)

    initial = client.get("/api/research/weights").json()
    assert initial["is_custom"] is False
    custom = initial["current"]
    custom["sectors"]["Biotechnology"]["valuation"] = 5
    custom["sectors"]["Biotechnology"]["momentum"] = 15

    updated = client.put("/api/research/weights", json=custom)

    assert updated.status_code == 200
    assert updated.json()["is_custom"] is True
    assert updated.json()["current"]["sectors"]["Biotechnology"]["momentum"] == 15
    assert client.delete("/api/research/weights").json()["is_custom"] is False


def test_research_weights_reject_invalid_total(tmp_path):
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)
    config = client.get("/api/research/weights").json()["current"]
    config["generic"]["valuation"] = 19

    response = client.put("/api/research/weights", json=config)

    assert response.status_code == 400
    assert "total 100%" in response.json()["detail"]


def test_research_company_returns_evidence_and_source_ledger(tmp_path):
    database_path = tmp_path / "app.db"
    app = create_app(database_path=str(database_path))
    _write_universe(tmp_path / "research_universe_120.csv")
    run_id = _seed_research_run(database_path)
    client = TestClient(app)

    response = client.get(f"/api/research/companies/AAA?run_id={run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["company"]["company"] == "Alpha Corp"
    assert payload["score"]["ticker"] == "AAA"
    assert payload["provider_highlights"]["seeking_alpha"][0]["value"] == "buy"
    assert len(payload["sources"]) == 2
    assert next(item for item in payload["sources"] if item["status"] == "failed")["failure_reason"] == "Blocked page"


def test_research_runs_only_lists_runs_with_enrichments(tmp_path):
    database_path = tmp_path / "app.db"
    app = create_app(database_path=str(database_path))
    run_id = _seed_research_run(database_path)
    client = TestClient(app)

    response = client.get("/api/research/runs")

    assert response.status_code == 200
    assert response.json()["runs"][0]["id"] == run_id
    assert response.json()["runs"][0]["ticker_count"] == 1


def test_research_csv_export_applies_filters(tmp_path):
    database_path = tmp_path / "app.db"
    app = create_app(database_path=str(database_path))
    _write_universe(tmp_path / "research_universe_120.csv")
    run_id = _seed_research_run(database_path)
    client = TestClient(app)

    response = client.get(f"/api/research/export.csv?run_id={run_id}&search=Alpha")

    assert response.status_code == 200
    assert "research-universe-run" in response.headers["content-disposition"]
    assert "AAA" in response.text
    assert "BBB" not in response.text
    assert "moat_evidence" in response.text


def test_sector_cohort_rank_requires_five_eligible_companies():
    companies = [
        {
            "ticker": f"E{index}",
            "sector": "Energy",
            "composite_score": score,
            "comparable_rank_eligible": True,
        }
        for index, score in enumerate((80, 70, 60, 50, 40), start=1)
    ]
    companies.append(
        {
            "ticker": "M1",
            "sector": "Materials",
            "composite_score": 90,
            "comparable_rank_eligible": True,
        }
    )

    _apply_sector_cohort_ranks(companies)

    assert companies[0]["sector_rank"] == 1
    assert companies[0]["sector_percentile"] == 100.0
    assert companies[4]["sector_rank"] == 5
    assert companies[4]["sector_percentile"] == 0.0
    assert companies[5]["sector_rank"] is None
    assert companies[5]["sector_cohort_size"] == 1


def test_bulk_extraction_only_processes_companies_without_records(tmp_path):
    database_path = tmp_path / "app.db"
    repository = RunRepository(str(database_path))

    class FakeEnricher:
        def __init__(self):
            self.calls = []

        def enrich_ticker(self, run_id, ticker, asset_type=None):
            self.calls.append((ticker, asset_type))
            repository.save_ticker_enrichment(
                run_id,
                ticker,
                "seeking_alpha",
                "quant",
                {"provider": "seeking_alpha", "rating_type": "quant", "ticker": ticker, "rating": "buy"},
            )
            return {"attempted": 1, "saved": 1, "failed": 0}

    enricher = FakeEnricher()
    app = create_app(
        database_path=str(database_path),
        run_orchestrator=SimpleNamespace(rating_enricher=enricher),
    )
    _write_universe(tmp_path / "research_universe_120.csv")
    run_id = _seed_research_run(database_path)
    app.state.browser_task_queue.mark_extension_seen()
    client = TestClient(app)

    response = client.post(f"/api/research/bulk-extraction/start?run_id={run_id}")
    deadline = time.time() + 2
    status = response.json()
    while status["status"] == "running" and time.time() < deadline:
        time.sleep(0.01)
        status = client.get("/api/research/bulk-extraction/status").json()

    assert response.status_code == 200
    assert status["status"] == "completed"
    assert status["total"] == 1
    assert enricher.calls == [("BBB", "stock")]


def test_bulk_extraction_order_prioritizes_new_york_listings_then_priority():
    exchanges = {"ADR": "NYSE", "OTC": "OTC MARKETS", "LSE": "LONDON"}
    companies = [
        {"ticker": "OTC", "priority": 99},
        {"ticker": "LSE", "priority": 100},
        {"ticker": "ADR", "priority": 50},
    ]

    ordered = sorted(companies, key=lambda company: _bulk_extraction_order(company, exchanges))

    assert [company["ticker"] for company in ordered] == ["ADR", "OTC", "LSE"]


def test_recoverable_source_retry_only_requests_parser_and_temporary_pages(tmp_path):
    database_path = tmp_path / "app.db"
    repository = RunRepository(str(database_path))

    class FakeEnricher:
        def __init__(self):
            self.calls = []

        def enrich_ticker(
            self,
            run_id,
            ticker,
            asset_type=None,
            target_keys=None,
            zacks_forecast_for_detailed_estimates=False,
        ):
            self.calls.append(
                (ticker, asset_type, target_keys, zacks_forecast_for_detailed_estimates)
            )
            for provider, data_type in target_keys or set():
                repository.save_ticker_enrichment(
                    run_id,
                    ticker,
                    provider,
                    data_type,
                    {"provider": provider, "rating_type": data_type, "ticker": ticker},
                )
            return {"attempted": len(target_keys or set()), "saved": len(target_keys or set()), "failed": 0}

    enricher = FakeEnricher()
    app = create_app(
        database_path=str(database_path),
        run_orchestrator=SimpleNamespace(rating_enricher=enricher),
    )
    _write_universe(tmp_path / "research_universe_120.csv")
    run_id = _seed_research_run(database_path)
    repository.save_ticker_enrichment(
        run_id, "AAA", "zacks", "quote", {}, status="failed",
        failure_reason="Rating data unavailable from source coverage",
    )
    repository.save_ticker_enrichment(
        run_id, "AAA", "seeking_alpha", "income_statement", {}, status="failed",
        failure_reason="No rating snapshot parsed from page text",
    )
    repository.save_ticker_enrichment(
        run_id, "AAA", "investing_pro", "forecast", {}, status="failed",
        failure_reason="Source temporarily unavailable",
    )
    repository.save_ticker_enrichment(
        run_id, "AAA", "zacks", "detailed_estimates", {}, status="failed",
        failure_reason="Source access blocked (HTTP 403)",
    )
    app.state.browser_task_queue.mark_extension_seen()
    client = TestClient(app)

    response = client.post(f"/api/research/source-issues/retry?run_id={run_id}")
    deadline = time.time() + 2
    status = response.json()
    while status["status"] == "running" and time.time() < deadline:
        time.sleep(0.01)
        status = client.get("/api/research/bulk-extraction/status").json()

    assert response.status_code == 200
    assert status["status"] == "completed"
    assert enricher.calls == [(
        "AAA",
        "stock",
        {("seeking_alpha", "income_statement"), ("investing_pro", "forecast")},
        False,
    )]

    blocked_response = client.post(
        f"/api/research/source-issues/retry?run_id={run_id}&include_access_blocked=true"
    )
    blocked_status = blocked_response.json()
    deadline = time.time() + 2
    while blocked_status["status"] == "running" and time.time() < deadline:
        time.sleep(0.01)
        blocked_status = client.get("/api/research/bulk-extraction/status").json()

    assert blocked_response.status_code == 200
    assert blocked_status["status"] == "completed"
    assert enricher.calls[-1] == (
        "AAA",
        "stock",
        {("zacks", "detailed_estimates")},
        True,
    )


def test_source_issue_classifier_distinguishes_coverage_access_parser_and_temporary():
    base = {"status": "failed", "failure_reason": "No rating snapshot parsed from page text"}

    assert classify_source_issue({**base, "data": {"page_title": "Zacks Search Results"}}) == "coverage_unavailable"
    assert classify_source_issue({**base, "data": {"page_title": "403 Forbidden"}}) == "access_blocked"
    assert classify_source_issue({**base, "data": {"page_title": "Normal financial statement"}}) == "parser_gap"
    assert classify_source_issue({**base, "data": {"page_title": "Temporarily down for maintenance"}}) == "temporary"
    assert classify_source_issue({"status": "ready"}) is None
    assert classify_source_issue({"status": "not_applicable"}) == "coverage_unavailable"
    assert classify_source_issue({
        **base,
        "provider": "seeking_alpha",
        "data_type": "growth",
        "data": {"page_title": "ANCTF Growth Grade", "text_char_count": 4500},
    }) == "parser_gap"
    assert classify_source_issue({
        **base,
        "provider": "seeking_alpha",
        "data_type": "author_ratings",
        "data": {"text_sample": "We currently have no SA Analysts Ratings on this stock."},
    }) == "coverage_unavailable"
    assert classify_source_issue({
        **base,
        "provider": "investing_pro",
        "data_type": "options_chain",
        "failure_reason": "Investing.com redirected away from the verified instrument route",
    }) == "coverage_unavailable"
    assert classify_source_issue({
        **base,
        "failure_reason": "User Chrome article extraction failed: Tabs cannot be edited right now",
    }) == "temporary"
    assert classify_source_issue({
        **base,
        "provider": "zacks",
        "data_type": "quote",
        "source_url": "https://www.zacks.com/funds/etf/QQQ/profile",
    }) == "coverage_unavailable"
    assert classify_source_issue({
        **base,
        "provider": "zacks",
        "data_type": "insider_transactions",
        "data": {
            "page_title": "CNQ: Canadian Natural Resources - Insider Transations - Zacks.com",
            "text_char_count": 7514,
        },
    }) == "coverage_unavailable"
