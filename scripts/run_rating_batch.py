from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
import time

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from email_article_analyzer.config import AppConfig  # noqa: E402
from email_article_analyzer.rating_enrichment import required_enrichment_data_types  # noqa: E402
from email_article_analyzer.repositories import RunRepository, WatchlistRepository  # noqa: E402


STATE_PATH = ROOT / "data" / "rating_batch_state.json"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
INVESTING_MAPPING_PATH = ROOT / "data" / "investing_instrument_mapping.csv"


def bridge_connected(client: httpx.Client, base_url: str) -> bool:
    response = client.get(f"{base_url}/api/browser-tasks/status")
    response.raise_for_status()
    return response.json().get("status") == "connected"


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"run_id": None, "completed": {}, "failed": {}}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = STATE_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(STATE_PATH)


def load_investing_tickers() -> set[str]:
    if not INVESTING_MAPPING_PATH.exists():
        return set()
    with INVESTING_MAPPING_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            str(row.get("ticker") or "").strip().upper()
            for row in csv.DictReader(handle)
            if row.get("canonical_url")
        }


def load_universe_file(path: Path) -> dict[str, dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    universe = {}
    for row in rows:
        normalized_keys = {str(key).strip().lower(): value for key, value in row.items()}
        ticker = str(normalized_keys.get("ticker") or normalized_keys.get("symbol") or "").strip().upper()
        if not ticker:
            continue
        universe[ticker] = {
            "normalized_ticker": ticker,
            "asset_type": str(normalized_keys.get("asset_type") or "stock").strip().lower(),
            "priority": _number(normalized_keys.get("priority")),
        }
    if not universe:
        raise ValueError(f"No Ticker or Symbol values found in universe file: {path}")
    return universe


def load_investing_mappings() -> dict[str, dict[str, str]]:
    if not INVESTING_MAPPING_PATH.exists():
        return {}
    with INVESTING_MAPPING_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            str(row.get("ticker") or "").strip().upper(): row
            for row in csv.DictReader(handle)
            if row.get("canonical_url")
        }


def research_order(item: tuple[str, dict], mappings: dict[str, dict[str, str]]) -> tuple:
    ticker, metadata = item
    mapping = mappings.get(ticker, {})
    exchange = str(mapping.get("exchange") or "").strip().upper()
    if exchange in {"NYSE", "NASDAQ", "NYSE AMERICAN", "AMEX"}:
        listing_rank = 0
    elif exchange == "OTC MARKETS":
        listing_rank = 1
    elif exchange:
        listing_rank = 2
    else:
        listing_rank = 3
    return (listing_rank, -float(metadata.get("priority") or 0), ticker)


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in {None, ""} else None
    except (TypeError, ValueError):
        return None


def has_complete_research(
    repository: RunRepository,
    run_id: int,
    ticker: str,
    asset_type: str | None,
    investing_tickers: set[str],
    include_polygon: bool,
) -> bool:
    required = required_enrichment_data_types(
        asset_type=asset_type,
        include_polygon=include_polygon,
        include_research=True,
        include_investing=ticker in investing_tickers,
    )
    return repository.has_complete_ticker_enrichments(
        run_id,
        ticker,
        required_data_types=required,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Resumable SA/Zacks enrichment for the active watchlist.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum new tickers to process in this invocation.")
    parser.add_argument("--ticker", action="append", default=[], help="Process only the specified ticker; may be repeated.")
    parser.add_argument("--delay", type=float, default=1.5, help="Delay between tickers in seconds.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--universe-file",
        type=Path,
        help="Stable CSV research universe. Keeps the batch independent of mutable app watchlist uploads.",
    )
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument(
        "--force-completed",
        action="store_true",
        help="Reprocess requested tickers even when they already appear in completed state.",
    )
    args = parser.parse_args()

    config = AppConfig.from_env()
    run_repo = RunRepository(config.database_path)
    if args.universe_file:
        watchlist_by_ticker = load_universe_file(args.universe_file)
    else:
        watchlist = WatchlistRepository(config.database_path).list_active_items()
        watchlist_by_ticker = {
            str(item["normalized_ticker"]).upper(): item
            for item in watchlist
        }
    investing_mappings = load_investing_mappings()
    ordered_watchlist = sorted(
        watchlist_by_ticker.items(),
        key=lambda item: research_order(item, investing_mappings),
    )
    all_tickers = [ticker for ticker, _metadata in ordered_watchlist]
    tickers = list(all_tickers)
    requested = {value.strip().upper() for value in args.ticker if value.strip()}
    if requested:
        tickers = [ticker for ticker in tickers if ticker in requested]

    state = load_state()
    if state.get("run_id") is None:
        state["run_id"] = run_repo.create_run("paid-rating-batch", "paid-rating-batch")
        save_state(state)
    run_id = int(state["run_id"])

    completed = state.setdefault("completed", {})
    failed = state.setdefault("failed", {})
    investing_tickers = set(investing_mappings)
    include_polygon = bool(config.polygon_api_key)
    pending = [
        ticker
        for ticker in tickers
        if args.force_completed
        or not has_complete_research(
            run_repo,
            run_id,
            ticker,
            watchlist_by_ticker[ticker].get("asset_type"),
            investing_tickers,
            include_polygon,
        )
    ]
    if not args.retry_failed:
        pending = [ticker for ticker in pending if ticker not in failed]
    if args.limit is not None:
        pending = pending[: max(0, args.limit)]

    print(
        json.dumps(
            {
                "run_id": run_id,
                "selected": len(tickers),
                "full_watchlist": len(all_tickers),
                "pending_this_run": len(pending),
            }
        )
    )
    with httpx.Client(timeout=httpx.Timeout(700.0, connect=10.0)) as client:
        if pending and not bridge_connected(client, args.base_url):
            print(json.dumps({"error": "Chrome extension bridge is not connected; batch not started."}))
            return 2
        for index, ticker in enumerate(pending, start=1):
            url = f"{args.base_url}/api/runs/{run_id}/retry-enrichments"
            print(f"[{index}/{len(pending)}] {ticker}", flush=True)
            try:
                if not bridge_connected(client, args.base_url):
                    raise RuntimeError("Chrome extension bridge disconnected; stopping batch.")
                response = client.post(
                    url,
                    params={
                        "ticker": ticker,
                        "force": "true",
                        "allow_unlisted": "true" if args.universe_file else "false",
                    },
                )
                response.raise_for_status()
                payload = response.json()
                result = next((item for item in payload.get("results", []) if item.get("ticker") == ticker), {})
                if not result or int(result.get("attempted", 0)) <= 0:
                    raise RuntimeError(
                        "Enrichment API returned no attempted work for the requested ticker."
                    )
                summary = {
                    "attempted": int(result.get("attempted", 0)),
                    "saved": int(result.get("saved", 0)),
                    "failed": int(result.get("failed", 0)),
                    "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                if summary["saved"] <= 1 and summary["failed"] >= 5:
                    raise RuntimeError(
                        f"Paid-page enrichment did not complete (saved={summary['saved']}, "
                        f"failed={summary['failed']})."
                    )
                completed[ticker] = summary
                failed.pop(ticker, None)
                print(json.dumps({"ticker": ticker, **summary}), flush=True)
            except Exception as exc:
                failed[ticker] = {
                    "error": str(exc),
                    "failed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                print(json.dumps({"ticker": ticker, "error": str(exc)}), flush=True)
                save_state(state)
                if "bridge disconnected" in str(exc).lower():
                    break
            save_state(state)
            if index < len(pending):
                time.sleep(max(0.0, args.delay))

    complete_count = sum(
        has_complete_research(
            run_repo,
            run_id,
            ticker,
            watchlist_by_ticker[ticker].get("asset_type"),
            investing_tickers,
            include_polygon,
        )
        for ticker in all_tickers
    )
    all_done = complete_count == len(all_tickers)
    if all_done:
        run_repo.complete_run_if_running(run_id, status="completed")
    print(
        json.dumps(
            {
                "run_id": run_id,
                "research_complete": complete_count,
                "full_watchlist": len(all_tickers),
                "failed": len(failed),
                "all_done": all_done,
            }
        )
    )
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
