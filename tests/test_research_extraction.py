import time

from email_article_analyzer.research_extraction import BulkResearchExtractionManager


def _wait_for_terminal(manager, timeout=2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = manager.status()
        if status["status"] in {"completed", "stopped"}:
            return status
        time.sleep(0.01)
    raise AssertionError("Bulk extraction did not finish")


def test_bulk_research_extraction_processes_each_ticker_and_tracks_failures():
    manager = BulkResearchExtractionManager()

    def worker(ticker):
        if ticker == "BAD":
            raise RuntimeError("blocked")
        return {"attempted": 22, "saved": 20, "failed": 0}

    started = manager.start(51, ["AAA", "BAD", "BBB"], worker)
    completed = _wait_for_terminal(manager)

    assert started["status"] == "running"
    assert completed["status"] == "completed"
    assert completed["processed"] == 3
    assert completed["succeeded"] == 2
    assert completed["failed"] == 1
    assert completed["completed_tickers"] == ["AAA", "BBB"]
    assert completed["failures"] == [{"ticker": "BAD", "error": "blocked"}]


def test_bulk_research_extraction_can_stop_between_companies():
    manager = BulkResearchExtractionManager()

    def worker(ticker):
        manager.request_stop()
        return {"attempted": 22, "saved": 20, "failed": 0}

    manager.start(51, ["AAA", "BBB"], worker)
    stopped = _wait_for_terminal(manager)

    assert stopped["status"] == "stopped"
    assert stopped["processed"] == 1
    assert stopped["completed_tickers"] == ["AAA"]


def test_source_issue_retry_tracks_record_level_progress():
    manager = BulkResearchExtractionManager()

    manager.start(
        51,
        ["AAA"],
        lambda _ticker: {"attempted": 2, "saved": 2, "failed": 0},
        job_type="source_issue_retry",
        requested_records=2,
    )
    completed = _wait_for_terminal(manager)

    assert completed["job_type"] == "source_issue_retry"
    assert completed["requested_records"] == 2
    assert completed["saved_records"] == 2
    assert completed["failed_records"] == 0


def test_source_issue_retry_counts_partial_results_even_when_company_fails():
    manager = BulkResearchExtractionManager()

    manager.start(
        51,
        ["PARTIAL", "FAILED"],
        lambda ticker: (
            {"attempted": 6, "saved": 1, "failed": 5}
            if ticker == "PARTIAL"
            else {"attempted": 2, "saved": 0, "failed": 2}
        ),
        job_type="source_issue_retry",
        requested_records=8,
    )
    completed = _wait_for_terminal(manager)

    assert completed["succeeded"] == 1
    assert completed["failed"] == 1
    assert completed["attempted_records"] == 8
    assert completed["saved_records"] == 1
    assert completed["failed_records"] == 7
