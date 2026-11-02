from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import inspect
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.responses import Response

from email_article_analyzer.api.dashboard import STATIC_DIR
from email_article_analyzer.db import connect
from email_article_analyzer.investment_scoring import CATEGORY_WEIGHTS
from email_article_analyzer.investment_scoring import score_company_research
from email_article_analyzer.repositories import RunRepository
from email_article_analyzer.sector_scoring import MINIMUM_COHORT_SIZE
from email_article_analyzer.sector_scoring import SECTOR_LIMITATIONS
from email_article_analyzer.sector_scoring import SECTOR_BENCHMARKS
from email_article_analyzer.sector_scoring import SECTOR_MODEL_VERSION
from email_article_analyzer.sector_scoring import apply_sector_models
from email_article_analyzer.scoring_config import is_custom_scoring_config
from email_article_analyzer.scoring_config import load_scoring_config
from email_article_analyzer.scoring_config import recommended_scoring_config
from email_article_analyzer.scoring_config import reset_scoring_config
from email_article_analyzer.scoring_config import save_scoring_config
from email_article_analyzer.watchlist import normalize_ticker


router = APIRouter(tags=["research"])


@router.get("/research", response_class=HTMLResponse)
def research_dashboard() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "research.html").read_text(encoding="utf-8"))


@router.get("/api/research/runs")
def list_research_runs(request: Request) -> dict[str, Any]:
    with connect(request.app.state.database_path) as conn:
        rows = conn.execute(
            """
            SELECT runs.*, COUNT(ticker_enrichments.id) AS enrichment_count,
                   COUNT(DISTINCT ticker_enrichments.ticker) AS ticker_count
            FROM runs
            JOIN ticker_enrichments ON ticker_enrichments.run_id = runs.id
            GROUP BY runs.id
            ORDER BY runs.id DESC
            """
        ).fetchall()
    return {"runs": [dict(row) for row in rows]}


@router.get("/api/research/bulk-extraction/status")
def bulk_extraction_status(request: Request) -> dict[str, Any]:
    return request.app.state.bulk_research_extraction.status()


@router.get("/api/research/weights")
def research_weights(request: Request) -> dict[str, Any]:
    current = _scoring_config(request)
    return {
        "current": current,
        "recommended": recommended_scoring_config(),
        "is_custom": is_custom_scoring_config(current),
    }


@router.put("/api/research/weights")
def update_research_weights(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    try:
        current = save_scoring_config(
            Path(request.app.state.research_scoring_config_path),
            payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "current": current,
        "recommended": recommended_scoring_config(),
        "is_custom": is_custom_scoring_config(current),
    }


@router.delete("/api/research/weights")
def reset_research_weights(request: Request) -> dict[str, Any]:
    current = reset_scoring_config(Path(request.app.state.research_scoring_config_path))
    return {
        "current": current,
        "recommended": recommended_scoring_config(),
        "is_custom": False,
    }


@router.post("/api/research/bulk-extraction/start")
def start_bulk_extraction(
    request: Request,
    run_id: int = Query(ge=1),
) -> dict[str, Any]:
    manager = request.app.state.bulk_research_extraction
    if manager.status()["status"] in {"running", "stopping"}:
        raise HTTPException(status_code=409, detail="Bulk research extraction is already running")
    if request.app.state.run_control.active_run_id() is not None:
        raise HTTPException(status_code=409, detail="A discovery run is active; finish or stop it first")
    browser_queue = request.app.state.browser_task_queue
    if not browser_queue.is_extension_connected():
        raise HTTPException(status_code=409, detail="Browser bridge is not connected")
    rating_enricher = getattr(
        getattr(request.app.state, "run_orchestrator", None),
        "rating_enricher",
        None,
    )
    if rating_enricher is None:
        raise HTTPException(status_code=503, detail="Rating enricher is not configured")

    _run, companies, _records = _build_research_view(request, run_id)
    pending = [company for company in companies if company["record_count"] == 0]
    exchanges = _read_investing_exchanges(
        Path(request.app.state.research_universe_path).parent / "investing_instrument_mapping.csv"
    )
    pending.sort(key=lambda company: _bulk_extraction_order(company, exchanges))

    def worker(ticker: str) -> dict[str, int]:
        method = rating_enricher.enrich_ticker
        if "asset_type" in inspect.signature(method).parameters:
            return method(run_id=run_id, ticker=ticker, asset_type="stock")
        return method(run_id=run_id, ticker=ticker)

    try:
        return manager.start(run_id, [company["ticker"] for company in pending], worker)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/research/bulk-extraction/stop")
def stop_bulk_extraction(request: Request) -> dict[str, Any]:
    return request.app.state.bulk_research_extraction.request_stop()


@router.post("/api/research/source-issues/retry")
def retry_recoverable_source_issues(
    request: Request,
    run_id: int = Query(ge=1),
    include_access_blocked: bool = False,
    ticker: str | None = None,
) -> dict[str, Any]:
    manager = request.app.state.bulk_research_extraction
    if manager.status()["status"] in {"running", "stopping"}:
        raise HTTPException(status_code=409, detail="Another research extraction is already running")
    if request.app.state.run_control.active_run_id() is not None:
        raise HTTPException(status_code=409, detail="A discovery run is active; finish or stop it first")
    if not request.app.state.browser_task_queue.is_extension_connected():
        raise HTTPException(status_code=409, detail="Browser bridge is not connected")
    rating_enricher = getattr(
        getattr(request.app.state, "run_orchestrator", None),
        "rating_enricher",
        None,
    )
    if rating_enricher is None:
        raise HTTPException(status_code=503, detail="Rating enricher is not configured")

    _run, companies, records_by_ticker = _build_research_view(request, run_id)
    retry_kinds = {"access_blocked"} if include_access_blocked else {"parser_gap", "temporary"}
    targets_by_ticker: dict[str, set[tuple[str, str]]] = {}
    selected_ticker = normalize_ticker(ticker) if ticker else None
    for ticker, records in records_by_ticker.items():
        if selected_ticker and ticker != selected_ticker:
            continue
        for record in records:
            if classify_source_issue(record) not in retry_kinds:
                continue
            targets_by_ticker.setdefault(ticker, set()).add(
                (str(record["provider"]), str(record["data_type"]))
            )
    order = {company["ticker"]: index for index, company in enumerate(companies)}
    tickers = sorted(targets_by_ticker, key=lambda ticker: (order.get(ticker, 999999), ticker))

    def worker(ticker: str) -> dict[str, int]:
        method = rating_enricher.enrich_ticker
        kwargs: dict[str, Any] = {"run_id": run_id, "ticker": ticker}
        parameters = inspect.signature(method).parameters
        if "asset_type" in parameters:
            kwargs["asset_type"] = "stock"
        if "target_keys" in parameters:
            kwargs["target_keys"] = targets_by_ticker[ticker]
        if "zacks_forecast_for_detailed_estimates" in parameters:
            kwargs["zacks_forecast_for_detailed_estimates"] = (
                "zacks", "detailed_estimates"
            ) in targets_by_ticker[ticker]
        return method(**kwargs)

    try:
        return manager.start(
            run_id,
            tickers,
            worker,
            job_type="source_issue_retry",
            requested_records=sum(len(targets) for targets in targets_by_ticker.values()),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/research/universe")
def research_universe(
    request: Request,
    run_id: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    resolved_run_id = _resolve_run_id(request.app.state.database_path, run_id)
    run, companies, records_by_ticker = _build_research_view(request, resolved_run_id)
    scoring_config = _scoring_config(request)
    recommended_config = recommended_scoring_config()
    custom_weights = is_custom_scoring_config(scoring_config)
    model_version = "user_config_v1" if custom_weights else SECTOR_MODEL_VERSION
    ready_companies = [item for item in companies if item["comparable_rank_eligible"]]
    sector_model_ready = [item for item in companies if item["sector_model_rank_eligible"]]
    scored_companies = [item for item in companies if item["composite_score"] is not None]
    source_rows = [record for records in records_by_ticker.values() for record in records]
    source_issue_counts = {
        "coverage_unavailable": 0,
        "access_blocked": 0,
        "parser_gap": 0,
        "temporary": 0,
    }
    provider_absence_breakdown = {
        "sa_rating_not_supplied": 0,
        "zacks_ticker_not_supported": 0,
        "zacks_research_not_supplied": 0,
        "investing_page_not_found": 0,
        "other": 0,
    }
    for record in source_rows:
        issue_kind = classify_source_issue(record)
        if issue_kind:
            source_issue_counts[issue_kind] += 1
        if issue_kind == "coverage_unavailable":
            provider_absence_breakdown[_provider_absence_reason(record)] += 1
    sectors: dict[str, dict[str, int]] = {}
    for company in companies:
        sector = company["sector"] or "Unclassified"
        bucket = sectors.setdefault(
            sector,
            {"companies": 0, "extracted": 0, "rank_ready": 0, "sector_model_ready": 0},
        )
        bucket["companies"] += 1
        bucket["extracted"] += int(company["record_count"] > 0)
        bucket["rank_ready"] += int(company["comparable_rank_eligible"])
        bucket["sector_model_ready"] += int(company["sector_model_rank_eligible"])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run": run,
        "methodology": {
            "label": "Generic cross-sector research score",
            "category_weights": scoring_config["generic"],
            "recommended_category_weights": recommended_config["generic"],
            "scoring_config": {
                "is_custom": custom_weights,
                "current": scoring_config,
                "recommended": recommended_config,
            },
            "rank_eligibility": "At least 70% weighted coverage and 6 sufficient categories",
            "sector_model": {
                "version": model_version,
                "weights": scoring_config["sectors"],
                "recommended_weights": recommended_config["sectors"],
                "limitations": SECTOR_LIMITATIONS,
                "benchmarks": SECTOR_BENCHMARKS,
                "minimum_coverage": 0.70,
                "minimum_cohort_size": MINIMUM_COHORT_SIZE,
            },
            "warning": (
                "Sector models are provisional sensitivity frameworks and have not been backtested. "
                "Moat and pricing power are derived evidence scores, not provider ratings."
            ),
        },
        "summary": {
            "universe_count": len(companies),
            "companies_with_records": sum(item["record_count"] > 0 for item in companies),
            "scored_count": len(scored_companies),
            "rank_ready_count": len(ready_companies),
            "sector_model_ready_count": len(sector_model_ready),
            "average_score_coverage": round(
                sum(item["score_coverage"] for item in scored_companies) / len(scored_companies), 4
            ) if scored_companies else 0,
            "source_records": len(source_rows),
            "ready_source_records": sum(record["status"] == "ready" for record in source_rows),
            "failed_source_records": sum(record["status"] == "failed" for record in source_rows),
            "source_issue_counts": source_issue_counts,
            "provider_absence_breakdown": provider_absence_breakdown,
            "actionable_source_issues": (
                source_issue_counts["access_blocked"]
                + source_issue_counts["parser_gap"]
                + source_issue_counts["temporary"]
            ),
        },
        "sectors": [
            {
                "sector": name,
                **counts,
                "preliminary_cohort_ready": counts["rank_ready"] >= MINIMUM_COHORT_SIZE,
                "sector_model_cohort_ready": counts["sector_model_ready"] >= MINIMUM_COHORT_SIZE,
            }
            for name, counts in sorted(sectors.items())
        ],
        "companies": companies,
    }


@router.get("/api/research/companies/{ticker}")
def research_company(
    ticker: str,
    request: Request,
    run_id: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    normalized = normalize_ticker(ticker)
    resolved_run_id = _resolve_run_id(request.app.state.database_path, run_id)
    run, companies, records_by_ticker = _build_research_view(request, resolved_run_id)
    company = next((item for item in companies if item["ticker"] == normalized), None)
    if company is None:
        raise HTTPException(status_code=404, detail=f"Research company not found: {normalized}")
    records = records_by_ticker.get(normalized, [])
    ready_research = [
        dict(record.get("data") or {})
        for record in records
        if record["status"] == "ready" and record["provider"] != "polygon"
    ]
    scoring_config = _scoring_config(request)
    score = score_company_research(ready_research, scoring_config["generic"]) if ready_research else None
    return {
        "run": run,
        "company": company,
        "score": score,
        "provider_highlights": _provider_highlights(ready_research),
        "sources": [
            {
                "provider": record["provider"],
                "data_type": record["data_type"],
                "status": record["status"],
                "source_url": record.get("source_url"),
                "failure_reason": record.get("failure_reason"),
                "issue_kind": classify_source_issue(record),
                "updated_at": record.get("updated_at") or record.get("created_at"),
            }
            for record in records
        ],
    }


@router.get("/api/research/export.csv")
def export_research_universe(
    request: Request,
    run_id: int | None = Query(default=None, ge=1),
    search: str = "",
    sector: str = "",
    status: str = "",
    min_coverage: float = Query(default=0, ge=0, le=1),
) -> Response:
    resolved_run_id = _resolve_run_id(request.app.state.database_path, run_id)
    _run, companies, _records = _build_research_view(request, resolved_run_id)
    search_value = search.strip().lower()
    filtered = [
        company for company in companies
        if (
            (not search_value or search_value in company["ticker"].lower() or search_value in company["company"].lower())
            and (not sector or company["sector"] == sector)
            and (not status or company["research_status"] == status)
            and company["score_coverage"] >= min_coverage
        )
    ]
    category_names = list(CATEGORY_WEIGHTS)
    output = io.StringIO(newline="")
    fieldnames = [
        "generic_rank", "sector_rank", "sector_percentile", "sector_cohort_size",
        "sector_model_rank", "sector_model_score", "sector_model_coverage",
        "sector_model_percentile", "sector_model_cohort_size", "sector_model_version",
        "ticker", "company", "sector", "composite_score", "score_coverage",
        "research_status", "record_count", "failed_record_count", "freshest_at", *category_names,
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for company in filtered:
        writer.writerow(
            {
                **{name: company.get(name) for name in fieldnames if name not in category_names},
                **{name: company["categories"].get(name) for name in category_names},
            }
        )
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="research-universe-run-{resolved_run_id}.csv"'},
    )


def _resolve_run_id(database_path: str, requested_run_id: int | None) -> int:
    if requested_run_id is not None:
        try:
            RunRepository(database_path).get_run(requested_run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return requested_run_id
    with connect(database_path) as conn:
        row = conn.execute(
            """
            SELECT run_id
            FROM ticker_enrichments
            GROUP BY run_id
            ORDER BY run_id DESC
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No research enrichment run is available")
    return int(row["run_id"])


def _build_research_view(
    request: Request,
    run_id: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    repository = RunRepository(request.app.state.database_path)
    try:
        run = repository.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    records = repository.list_ticker_enrichments(run_id)
    scoring_config = _scoring_config(request)
    custom_weights = is_custom_scoring_config(scoring_config)
    records_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        records_by_ticker.setdefault(str(record["ticker"]).upper(), []).append(record)

    universe_path = Path(request.app.state.research_universe_path)
    universe = _read_universe(universe_path)
    known = {item["ticker"] for item in universe}
    for ticker in sorted(set(records_by_ticker) - known):
        universe.append({"ticker": ticker, "company": ticker, "sector": "Unclassified", "priority": None, "notes": "Observed in selected run"})

    companies = []
    for item in universe:
        ticker_records = records_by_ticker.get(item["ticker"], [])
        ready_research = [
            dict(record.get("data") or {})
            for record in ticker_records
            if record["status"] == "ready" and record["provider"] != "polygon"
        ]
        score = score_company_research(ready_research, scoring_config["generic"]) if ready_research else None
        source_counts: dict[str, dict[str, int]] = {}
        source_issue_counts = {
            "coverage_unavailable": 0,
            "access_blocked": 0,
            "parser_gap": 0,
            "temporary": 0,
        }
        for record in ticker_records:
            provider = str(record["provider"])
            bucket = source_counts.setdefault(provider, {"ready": 0, "failed": 0, "other": 0})
            status = str(record["status"])
            bucket[status if status in {"ready", "failed"} else "other"] += 1
            issue_kind = classify_source_issue(record)
            if issue_kind:
                source_issue_counts[issue_kind] += 1
        companies.append(
            {
                **item,
                "composite_score": score["composite_score"] if score else None,
                "score_coverage": score["score_coverage"] if score else 0,
                "comparable_rank_eligible": score["comparable_rank_eligible"] if score else False,
                "categories": {
                    name: category["score"] for name, category in (score["categories"] if score else {}).items()
                },
                "record_count": len(ticker_records),
                "ready_record_count": sum(record["status"] == "ready" for record in ticker_records),
                "failed_record_count": sum(record["status"] == "failed" for record in ticker_records),
                "source_counts": source_counts,
                "source_issue_counts": source_issue_counts,
                "freshest_at": max(
                    (record.get("updated_at") or record.get("created_at") or "" for record in ticker_records),
                    default=None,
                ),
                "research_status": (
                    "rank_ready" if score and score["comparable_rank_eligible"]
                    else "partial" if ticker_records else "pending"
                ),
            }
        )
    eligible = sorted(
        (item for item in companies if item["comparable_rank_eligible"]),
        key=lambda item: -(item["composite_score"] or 0),
    )
    ranks = {item["ticker"]: index for index, item in enumerate(eligible, start=1)}
    for item in companies:
        item["generic_rank"] = ranks.get(item["ticker"])
    _apply_sector_cohort_ranks(companies)
    apply_sector_models(
        companies,
        sector_weights=scoring_config["sectors"],
        model_version="user_config_v1" if custom_weights else SECTOR_MODEL_VERSION,
    )
    companies.sort(key=lambda item: (item["generic_rank"] is None, item["generic_rank"] or 9999, item["ticker"]))
    return run, companies, records_by_ticker


def _scoring_config(request: Request) -> dict[str, Any]:
    return load_scoring_config(Path(request.app.state.research_scoring_config_path))


def _apply_sector_cohort_ranks(companies: list[dict[str, Any]], minimum_size: int = 5) -> None:
    cohorts: dict[str, list[dict[str, Any]]] = {}
    for company in companies:
        company["sector_rank"] = None
        company["sector_percentile"] = None
        company["sector_cohort_size"] = 0
        company["sector_rank_eligible"] = False
        if company.get("comparable_rank_eligible"):
            cohorts.setdefault(str(company.get("sector") or "Unclassified"), []).append(company)
    for cohort in cohorts.values():
        cohort.sort(key=lambda item: (-(item.get("composite_score") or 0), item["ticker"]))
        size = len(cohort)
        for company in cohort:
            company["sector_cohort_size"] = size
        if size < minimum_size:
            continue
        for rank, company in enumerate(cohort, start=1):
            company["sector_rank"] = rank
            company["sector_percentile"] = round((size - rank) / (size - 1) * 100, 1)
            company["sector_rank_eligible"] = True


def classify_source_issue(record: dict[str, Any]) -> str | None:
    if record.get("status") == "not_applicable":
        return "coverage_unavailable"
    if record.get("status") != "failed":
        return None
    data = record.get("data") or {}
    text = " ".join(
        str(value or "")
        for value in (
            record.get("failure_reason"),
            data.get("page_title"),
            data.get("text_sample"),
        )
    ).lower()
    data_type = str(record.get("data_type") or "")
    provider = str(record.get("provider") or "")
    source_url = str(record.get("source_url") or "").lower()
    page_title = str(data.get("page_title") or "").lower()
    text_char_count = int(data.get("text_char_count") or 0)
    if (
        provider == "zacks"
        and data_type == "insider_transactions"
        and text_char_count >= 3000
        and "insider trans" in page_title
        and "no rating snapshot parsed" in text
    ):
        return "coverage_unavailable"
    if (
        provider == "seeking_alpha"
        and data_type in {"valuation", "growth", "profitability", "momentum", "peers"}
        and text_char_count >= 3000
        and not any(marker in page_title for marker in ("403", "404", "temporarily", "access denied"))
    ):
        return "parser_gap"
    coverage_markers = (
        "unavailable from source coverage",
        "rating is not available",
        "ratings are not available",
        "no analyst coverage",
        "no sa analysts ratings",
        "no wall st. ratings",
        "no exact investing.com instrument candidate found",
        "zacks search results",
        "error 404",
        "page not found",
    )
    if any(marker in text for marker in coverage_markers):
        return "coverage_unavailable"
    if (
        provider == "investing_pro"
        and data_type == "options_chain"
        and "redirected away from the verified instrument route" in text
    ):
        return "coverage_unavailable"
    if provider == "zacks" and data_type == "quote" and "/funds/etf/" in source_url:
        return "coverage_unavailable"
    access_markers = (
        "source access blocked",
        "403 forbidden",
        "permission to access",
        "blocked by source bot",
        "pardon our interruption",
        "made us think you were a bot",
        "captcha",
    )
    if any(marker in text for marker in access_markers):
        return "access_blocked"
    temporary_markers = (
        "temporarily down for maintenance",
        "please check back soon",
        "temporarily unavailable",
        "failed to fetch",
        "tabs cannot be edited right now",
        "timed out",
        "timeout",
    )
    if any(marker in text for marker in temporary_markers):
        return "temporary"
    return "parser_gap"


def _provider_absence_reason(record: dict[str, Any]) -> str:
    provider = str(record.get("provider") or "")
    data_type = str(record.get("data_type") or "")
    data = record.get("data") or {}
    text = " ".join(
        str(value or "")
        for value in (record.get("failure_reason"), data.get("page_title"), data.get("text_sample"))
    ).lower()
    if provider == "zacks" and "zacks search results" in text:
        return "zacks_ticker_not_supported"
    if (
        provider == "zacks"
        and data_type == "insider_transactions"
        and "does not provide an insider-transaction table" in text
    ):
        return "zacks_research_not_supplied"
    if provider == "investing_pro" and ("error 404" in text or "page not found" in text):
        return "investing_page_not_found"
    if provider == "seeking_alpha" and data_type in {"ratings", "author_ratings", "sell_side_ratings"}:
        return "sa_rating_not_supplied"
    return "other"


def _read_universe(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result = []
    seen = set()
    for row in rows:
        ticker = normalize_ticker(row.get("Ticker") or row.get("ticker") or "")
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        priority_raw = row.get("Priority") or row.get("priority")
        try:
            priority = float(priority_raw) if priority_raw not in {None, ""} else None
        except (TypeError, ValueError):
            priority = None
        result.append(
            {
                "ticker": ticker,
                "company": row.get("Company") or row.get("company") or ticker,
                "sector": row.get("Sector") or row.get("sector") or "Unclassified",
                "priority": priority,
                "notes": row.get("Notes") or row.get("notes") or "",
            }
        )
    return result


def _read_investing_exchanges(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            normalize_ticker(row.get("ticker") or ""): str(row.get("exchange") or "").strip().upper()
            for row in csv.DictReader(handle)
            if row.get("ticker")
        }


def _bulk_extraction_order(company: dict[str, Any], exchanges: dict[str, str]) -> tuple[Any, ...]:
    exchange = exchanges.get(company["ticker"], "")
    if exchange in {"NYSE", "NASDAQ", "NYSE AMERICAN", "AMEX"}:
        listing_rank = 0
    elif exchange == "OTC MARKETS":
        listing_rank = 1
    elif exchange:
        listing_rank = 2
    else:
        listing_rank = 3
    return listing_rank, -(company.get("priority") or 0), company["ticker"]


def _provider_highlights(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_key = {(str(item.get("provider")), str(item.get("rating_type"))): item for item in records}
    highlights: dict[str, list[dict[str, Any]]] = {"seeking_alpha": [], "zacks": [], "investing_pro": []}
    for rating_type, label in (
        ("quant", "Quant rating"), ("analysts", "SA analysts"), ("wall_street", "Wall Street"),
        ("valuation_metrics", "Valuation grade"), ("growth_metrics", "Growth grade"),
        ("profitability_metrics", "Profitability grade"), ("momentum_metrics", "Momentum grade"),
        ("revisions", "Revisions grade"),
    ):
        record = by_key.get(("seeking_alpha", rating_type), {})
        value = record.get("rating") or record.get("grade")
        if value is not None:
            highlights["seeking_alpha"].append({"label": label, "value": value})
    zacks = by_key.get(("zacks", "detailed_estimates"), {})
    for label, value in (
        ("Zacks rank", zacks.get("zacks_rank")),
        ("Value style", (zacks.get("style_scores") or {}).get("value")),
        ("Growth style", (zacks.get("style_scores") or {}).get("growth")),
        ("Momentum style", (zacks.get("style_scores") or {}).get("momentum")),
        ("ESP", zacks.get("earnings_esp")),
    ):
        if value is not None:
            highlights["zacks"].append({"label": label, "value": value})
    forecast = by_key.get(("investing_pro", "forecast"), {})
    ratios = by_key.get(("investing_pro", "ratios"), {})
    for label, value in (
        ("Forecast", forecast.get("rating")),
        ("Fair value upside", forecast.get("fair_value_upside_pct")),
        ("Analyst target upside", forecast.get("analyst_target_upside_pct")),
        ("Ratio categories", len(ratios.get("categories") or {})),
    ):
        if value is not None:
            highlights["investing_pro"].append({"label": label, "value": value})
    return highlights
