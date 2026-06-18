from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from email_article_analyzer.repositories import RunRepository

router = APIRouter(prefix="/api/runs", tags=["runs"])


class CreateRunRequest(BaseModel):
    extraction_model: str | None = None
    summary_model: str | None = None


@router.post("")
def create_run(payload: CreateRunRequest, request: Request) -> dict[str, Any]:
    orchestrator = getattr(request.app.state, "run_orchestrator", None)
    if orchestrator is None:
        raise HTTPException(
            status_code=503,
            detail="Run orchestrator is not configured",
        )
    result = orchestrator.start_discovery_run(
        extraction_model=payload.extraction_model,
        summary_model=payload.summary_model,
    )
    return {
        "run_id": result.run_id,
        "status": result.status,
        "candidate_count": result.candidate_count,
        "needed_source_logins": result.needed_source_logins,
    }


@router.get("")
def list_runs(request: Request) -> dict[str, Any]:
    repository = RunRepository(request.app.state.database_path)
    return {
        "runs": [
            {
                **run,
                "counts": repository.discovery_counts(run["id"]),
            }
            for run in repository.list_recent_runs()
        ]
    }


@router.get("/{run_id}")
def get_run(run_id: int, request: Request) -> dict[str, Any]:
    repository = RunRepository(request.app.state.database_path)
    try:
        run = repository.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    return {
        "run": run,
        "counts": repository.discovery_counts(run_id),
        "events": repository.list_events(run_id),
        "articles": repository.list_discovered_articles(run_id),
    }
