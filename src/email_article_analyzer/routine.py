"""Scheduled routine: run one discovery pass, diff it against the last report, and email it."""

from typing import Any
import json
import os
import traceback

from google.oauth2.credentials import Credentials
import httpx

from email_article_analyzer.api.runs import _market_data_for_report
from email_article_analyzer.api.runs import _rating_data_for_report
from email_article_analyzer.auth import GMAIL_SCOPES
from email_article_analyzer.config import AppConfig
from email_article_analyzer.db import connect
from email_article_analyzer.db import initialize_database
from email_article_analyzer.gmail_send import own_address
from email_article_analyzer.gmail_send import send_email
from email_article_analyzer.orchestrator_factory import _build_gmail_service
from email_article_analyzer.repositories import RunRepository
from email_article_analyzer.report_pdf_export import _best_price_target
from email_article_analyzer.report_pdf_export import _is_usable_article
from email_article_analyzer.report_pdf_export import _most_common
from email_article_analyzer.report_pdf_export import _ticker_action_cards
from email_article_analyzer.report_pdf_export import build_run_pdf_report

ROUTINE_MAX_NEW_MESSAGES = 50
HIGH_CONFIDENCE = 0.70
_ACTION_BY_STANCE = {"buy_watch": "BUY", "sell_watch": "SELL", "avoid": "SELL", "hold": "HOLD"}


def build_snapshot(
    articles: list[dict[str, Any]],
    market_data_by_ticker: dict[str, dict[str, Any]],
    rating_data_by_ticker: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    usable = [article for article in articles if _is_usable_article(article)]
    snapshot: dict[str, dict[str, Any]] = {}
    for card in _ticker_action_cards(usable, market_data_by_ticker, rating_data_by_ticker):
        best_target = _best_price_target(card["price_targets"])
        snapshot[card["ticker"]] = {
            "stance": _most_common(card["stances"]) or "unclear",
            "confidence": max(card["confidences"] or [0]),
            "target_price": best_target.get("target_price") if best_target else None,
        }
    return snapshot


def diff_snapshots(
    previous: dict[str, dict[str, Any]] | None,
    current: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    changes: dict[str, list[str]] = {"stance": [], "target": [], "added": [], "dropped": []}
    if previous is None:
        return changes
    changes["added"] = sorted(current.keys() - previous.keys())
    changes["dropped"] = sorted(previous.keys() - current.keys())
    for ticker in sorted(current.keys() & previous.keys()):
        old, new = previous[ticker], current[ticker]
        if old["stance"] != new["stance"]:
            changes["stance"].append(f"{ticker}: {old['stance']} -> {new['stance']}")
        if old["target_price"] != new["target_price"]:
            changes["target"].append(
                f"{ticker}: {_format_target(old['target_price'])} -> {_format_target(new['target_price'])}"
            )
    return changes


def high_confidence_news(articles: list[dict[str, Any]]) -> list[str]:
    items = []
    for article in articles:
        analysis = article.get("analysis") or {}
        confidence = float(analysis.get("confidence") or 0)
        if confidence < HIGH_CONFIDENCE or not _is_usable_article(article):
            continue
        title = (article.get("content") or {}).get("title") or article.get("subject") or "Untitled article"
        items.append(f"{title} ({analysis.get('stance') or 'unclear'}, {confidence:.0%})")
    return items


def split_recommendations(
    snapshot: dict[str, dict[str, Any]],
) -> tuple[list[str], list[str]]:
    actionable: list[str] = []
    watch: list[str] = []
    for ticker, item in sorted(snapshot.items()):
        action = _ACTION_BY_STANCE.get(item["stance"])
        line = (
            f"{ticker}: {item['stance']}, confidence {item['confidence']:.0%}, "
            f"target {_format_target(item['target_price'])}"
        )
        if action and item["confidence"] >= HIGH_CONFIDENCE:
            actionable.append(f"{action} {line}")
        else:
            watch.append(line)
    return actionable, watch


def build_email_body(
    run_id: int,
    changes: dict[str, list[str]],
    news: list[str],
    actionable: list[str],
    watch: list[str],
    has_baseline: bool,
) -> str:
    lines = [f"Stock analysis report, run #{run_id}", "", "CHANGES SINCE LAST REPORT"]
    if not has_baseline:
        lines.append("First routine report, so there is nothing earlier to compare against.")
    else:
        lines.extend(_section_items("Stance changes", changes["stance"]))
        lines.extend(_section_items("Price target changes", changes["target"]))
        lines.extend(_section_items("Tickers added", changes["added"]))
        lines.extend(_section_items("Tickers not covered this run", changes["dropped"]))
    lines.extend(_section_items("New high-confidence news", news))
    lines.append("")
    lines.append("RECOMMENDATIONS (confidence 70% or higher)")
    lines.extend(actionable or ["No actionable calls this run."])
    lines.append("")
    lines.append("WATCH LIST (below 70% or no clear call)")
    lines.extend(watch or ["Nothing on the watch list."])
    lines.append("")
    lines.append("Full details are in the attached PDF.")
    return "\n".join(lines)


def load_latest_snapshot(database_path: str, before_run_id: int) -> dict[str, dict[str, Any]] | None:
    with connect(database_path) as conn:
        row = conn.execute(
            "SELECT payload_json FROM report_snapshots WHERE run_id < ? ORDER BY run_id DESC LIMIT 1",
            (before_run_id,),
        ).fetchone()
    return json.loads(row["payload_json"]) if row else None


def save_snapshot(database_path: str, run_id: int, snapshot: dict[str, dict[str, Any]]) -> None:
    with connect(database_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO report_snapshots (run_id, payload_json) VALUES (?, ?)",
            (run_id, json.dumps(snapshot, sort_keys=True)),
        )


def run_routine(
    config: AppConfig,
    max_new_messages: int = ROUTINE_MAX_NEW_MESSAGES,
    resend_run_id: int | None = None,
) -> int:
    initialize_database(config.database_path)
    credentials = Credentials.from_authorized_user_file(config.gmail_token_path, GMAIL_SCOPES)
    try:
        if resend_run_id is None:
            result = _start_run_on_server(max_new_messages)
        else:
            result = {"run_id": resend_run_id, "status": "completed"}
        if result["status"] == "failed":
            raise RuntimeError(f"Run #{result['run_id']} failed; check its events in the app")

        # Build a fresh Gmail connection: the one from before the run may have gone stale.
        service = _build_gmail_service(credentials)
        to_address = own_address(service)
        repository = RunRepository(config.database_path)
        run_id = int(result["run_id"])
        run = repository.get_run(run_id)
        articles = repository.list_discovered_articles(run_id)
        market = _market_data_for_report(repository, run_id)
        ratings = _rating_data_for_report(repository, run_id)
        pdf = build_run_pdf_report(
            run=run,
            counts=repository.discovery_counts(run_id),
            events=repository.list_events(run_id),
            articles=articles,
            market_data_by_ticker=market,
            rating_data_by_ticker=ratings,
        )
        snapshot = build_snapshot(articles, market, ratings)
        previous = load_latest_snapshot(config.database_path, run_id)
        save_snapshot(config.database_path, run_id, snapshot)
        actionable, watch = split_recommendations(snapshot)
        body = build_email_body(
            run_id=run_id,
            changes=diff_snapshots(previous, snapshot),
            news=high_confidence_news(articles),
            actionable=actionable,
            watch=watch,
            has_baseline=previous is not None,
        )
        send_email(
            service,
            to=to_address,
            subject=f"Stock analysis report #{run_id} ({result['status']})",
            body=body,
            attachment=(f"stock-report-run-{run_id}.pdf", pdf),
        )
        print(f"Run #{run_id} finished ({result['status']}); report emailed to {to_address}.")
        return 0
    except Exception:
        _send_failure_alert(credentials, traceback.format_exc())
        raise


def _start_run_on_server(max_new_messages: int) -> dict[str, Any]:
    # The app server owns the Chrome bridge, so the routine asks it to run the
    # analysis. The server holds the request open until the run finishes.
    base_url = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    response = httpx.post(
        f"{base_url}/api/runs",
        json={"max_new_messages": max_new_messages},
        timeout=httpx.Timeout(30.0, read=None),
    )
    if response.status_code != 200:
        raise RuntimeError(f"App server refused the run ({response.status_code}): {response.text}")
    return response.json()


def _send_failure_alert(credentials, details: str) -> None:
    try:
        service = _build_gmail_service(credentials)
        send_email(
            service,
            to=own_address(service),
            subject="Stock analysis routine FAILED",
            body=f"The scheduled analysis did not finish.\n\n{details}",
        )
    except Exception:
        print("Could not send the failure alert email.")


def _format_target(value: Any) -> str:
    return "none" if value is None else f"{float(value):g}"


def _section_items(title: str, items: list[str]) -> list[str]:
    if not items:
        return [f"{title}: none"]
    return [f"{title}:"] + [f"  - {item}" for item in items]
