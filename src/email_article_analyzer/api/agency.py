"""Read/trigger API for Meiri's agency (~/apps/agency). Localhost only, like the rest of this app.

- POST /api/agency/enrich     refresh research for given tickers (light = key ratings only, ~4 pages/ticker)
- GET  /api/agency/enrich/status
- GET  /api/agency/research   enrichment records since a timestamp (heavy option tables excluded)
- GET  /api/agency/scores     coverage-aware factor scores per ticker (this app's own scoring)
- GET  /api/agency/opinions   newsletter article stances since a timestamp
"""
import inspect
import json
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from email_article_analyzer.investment_scoring import score_company_research

router = APIRouter(prefix="/api/agency", tags=["agency"])

LIGHT_TARGETS = {
    ("seeking_alpha", "ratings"),
    ("seeking_alpha", "sell_side_ratings"),
    ("zacks", "quote"),
    ("investing_pro", "overview"),
}
HEAVY_TYPES = ("options_chain", "greeks_montage")


class EnrichItem(BaseModel):
    ticker: str
    asset_type: str | None = None


class EnrichRequest(BaseModel):
    items: list[EnrichItem]
    light: bool = True


def _db(request: Request) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{request.app.state.database_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@router.post("/enrich")
def enrich(payload: EnrichRequest, request: Request) -> dict[str, Any]:
    manager = request.app.state.bulk_research_extraction
    if manager.status().get("status") in {"running", "stopping"}:
        raise HTTPException(status_code=409, detail="A research extraction is already running")
    if request.app.state.run_control.active_run_id() is not None:
        raise HTTPException(status_code=409, detail="A discovery run is active")
    if not request.app.state.browser_task_queue.is_extension_connected():
        raise HTTPException(status_code=409, detail="Browser bridge is not connected")
    enricher = getattr(getattr(request.app.state, "run_orchestrator", None), "rating_enricher", None)
    if enricher is None:
        raise HTTPException(status_code=503, detail="Rating enricher is not configured")
    with _db(request) as conn:
        row = conn.execute("SELECT max(id) AS id FROM runs").fetchone()
    if not row or row["id"] is None:
        raise HTTPException(status_code=409, detail="No run exists yet")
    run_id = int(row["id"])
    assets = {i.ticker.strip().upper(): i.asset_type for i in payload.items if i.ticker.strip()}
    params = inspect.signature(enricher.enrich_ticker).parameters

    def worker(ticker: str) -> dict[str, int]:
        kwargs: dict[str, Any] = {"run_id": run_id, "ticker": ticker}
        if "asset_type" in params:
            kwargs["asset_type"] = assets.get(ticker) or "stock"
        if payload.light and "target_keys" in params:
            kwargs["target_keys"] = set(LIGHT_TARGETS)
        return enricher.enrich_ticker(**kwargs)

    try:
        return manager.start(run_id, list(assets), worker, job_type="agency_light" if payload.light else "agency_full")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/enrich/status")
def enrich_status(request: Request) -> dict[str, Any]:
    return request.app.state.bulk_research_extraction.status()


@router.get("/research")
def research(request: Request, since: str = Query("1970-01-01"), limit: int = Query(20000, le=50000)) -> dict[str, Any]:
    with _db(request) as conn:
        rows = conn.execute(
            f"""SELECT id, run_id, ticker, provider, data_type, status, failure_reason, data_json, created_at
                FROM ticker_enrichments WHERE created_at > ? AND data_type NOT IN ({",".join("?" * len(HEAVY_TYPES))})
                ORDER BY id LIMIT ?""",
            (since, *HEAVY_TYPES, limit),
        ).fetchall()
    return {"records": [{**{k: r[k] for k in r.keys() if k != "data_json"}, "data": json.loads(r["data_json"] or "{}")}
                        for r in rows]}


@router.get("/scores")
def scores(request: Request, days: int = Query(45, ge=1, le=365)) -> dict[str, Any]:
    """Latest ready record per (ticker, provider, data_type) within `days`, scored with score_company_research."""
    with _db(request) as conn:
        rows = conn.execute(
            """SELECT e.ticker, e.data_json FROM ticker_enrichments e
               JOIN (SELECT ticker, provider, data_type, max(id) AS id FROM ticker_enrichments
                     WHERE status='ready' AND provider <> 'polygon' AND created_at > datetime('now', ?)
                     GROUP BY ticker, provider, data_type) l ON l.id = e.id""",
            (f"-{days} days",),
        ).fetchall()
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r["ticker"].upper(), []).append(json.loads(r["data_json"] or "{}"))
    out = []
    for ticker, records in sorted(grouped.items()):
        res = score_company_research(records)
        out.append({"ticker": ticker, "composite_score": res["composite_score"], "score_coverage": res["score_coverage"],
                    "comparable": res["comparable_rank_eligible"],
                    "categories": {k: v["score"] for k, v in res["categories"].items()}})
    return {"scores": out}


@router.get("/opinions")
def opinions(request: Request, since: str = Query("1970-01-01")) -> dict[str, Any]:
    with _db(request) as conn:
        rows = conn.execute(
            """SELECT a.id, a.created_at, a.model, a.summary, a.stance, a.confidence, a.mentioned_tickers_json,
                      l.normalized_url AS url, l.source_key, m.subject, m.received_at
               FROM article_analyses a JOIN article_links l ON l.id = a.article_link_id
               JOIN gmail_messages m ON m.id = l.gmail_message_id
               WHERE a.created_at > ? ORDER BY a.id""",
            (since,),
        ).fetchall()
    return {"opinions": [{**{k: r[k] for k in r.keys() if k != "mentioned_tickers_json"},
                          "tickers": json.loads(r["mentioned_tickers_json"] or "[]")} for r in rows]}


@router.get("/routing")
def routing(request: Request, days: int = Query(7, ge=1, le=90)) -> dict[str, Any]:
    """Article routing health: paths taken, local-vs-GPT stance agreement, OpenAI spend (from openai_usage)."""
    with _db(request) as conn:
        rows = conn.execute(
            """SELECT stance, json_extract(raw_response_json,'$.routing.path') AS path,
                      json_extract(raw_response_json,'$.routing.reason') AS reason,
                      json_extract(raw_response_json,'$.routing.local_stance') AS local_stance
               FROM article_analyses WHERE created_at > datetime('now', ?)""", (f"-{days} days",)).fetchall()
        has_usage = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='openai_usage'").fetchone()
        usage = {"month_usd": 0.0, "window_usd": 0.0, "calls": 0}
        if has_usage:
            m = conn.execute("""SELECT coalesce(sum(est_cost_usd),0) usd, count(*) n FROM openai_usage
                                WHERE created_at >= strftime('%Y-%m-01','now')""").fetchone()
            w = conn.execute("SELECT coalesce(sum(est_cost_usd),0) usd FROM openai_usage WHERE created_at > datetime('now', ?)",
                             (f"-{days} days",)).fetchone()
            usage = {"month_usd": round(m["usd"], 4), "window_usd": round(w["usd"], 4), "calls": m["n"]}
    paths: dict[str, int] = {}
    pairs = agree = 0
    for r in rows:
        paths[r["path"] or "untagged"] = paths.get(r["path"] or "untagged", 0) + 1
        if r["path"] == "cloud" and r["local_stance"]:
            pairs += 1
            agree += r["local_stance"] == r["stance"]
    return {"days": days, "articles": len(rows), "paths": paths, "agreement_pairs": pairs,
            "agreement": round(agree / pairs, 3) if pairs else None, "openai": usage}
