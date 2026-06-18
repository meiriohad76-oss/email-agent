from tempfile import TemporaryDirectory
from pathlib import Path

from fastapi.testclient import TestClient

from email_article_analyzer.db import initialize_database
from email_article_analyzer.main import create_app
from email_article_analyzer.repositories import GmailDiscoveryRepository, RunRepository


def main() -> int:
    with TemporaryDirectory() as tmpdir:
        database_path = str(Path(tmpdir) / "app.db")
        initialize_database(database_path)
        run_repo = RunRepository(database_path)
        gmail_repo = GmailDiscoveryRepository(database_path)

        run_id = run_repo.create_run("smoke-extract", "smoke-summary")
        run_repo.complete_run(run_id)
        message_id = gmail_repo.save_message(
            run_id=run_id,
            gmail_message_id="smoke-msg-1",
            thread_id="smoke-thread-1",
            sender="alerts@seekingalpha.com",
            subject="Smoke Test Story",
            labels=["UNREAD"],
            source_key="seeking_alpha",
            processing_status="discovered",
        )
        article_link_id = gmail_repo.save_article_link(
            gmail_message_row_id=message_id,
            source_key="seeking_alpha",
            raw_url="https://seekingalpha.com/article/smoke",
            normalized_url="https://seekingalpha.com/article/smoke",
            detection_method="headline_anchor",
            detection_confidence=0.95,
            heuristic_notes=None,
        )
        gmail_repo.save_article_content(
            article_link_id=article_link_id,
            fetch_status="fetched",
            final_url="https://seekingalpha.com/article/smoke",
            http_status=200,
            title="Smoke Test Story",
            extracted_text="Revenue guidance improved and margins expanded.",
            failure_reason=None,
        )
        gmail_repo.save_article_analysis(
            article_link_id=article_link_id,
            provider="openai",
            model="smoke-summary",
            summary="Revenue guidance improved and margins expanded.",
            stance="buy_watch",
            confidence=0.81,
            supporting_evidence=["Revenue guidance improved", "Margins expanded"],
            mentioned_tickers=["NVDA"],
            raw_response={"source": "smoke"},
        )

        with TestClient(create_app(database_path=database_path)) as client:
            checks = [
                ("health", client.get("/api/health")),
                ("dashboard", client.get("/")),
                ("provider status", client.get("/api/status/providers")),
                ("runs", client.get("/api/runs")),
                ("run detail", client.get(f"/api/runs/{run_id}")),
            ]
            for label, response in checks:
                if response.status_code != 200:
                    raise RuntimeError(
                        f"{label} check failed with HTTP {response.status_code}: {response.text}"
                    )

            detail = checks[-1][1].json()
            article = detail["articles"][0]
            if article["analysis"]["stance"] != "buy_watch":
                raise RuntimeError("Run detail did not include the seeded analysis result")
            if article["content"]["fetch_status"] != "fetched":
                raise RuntimeError("Run detail did not include the seeded content result")

    print("Live product smoke check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
