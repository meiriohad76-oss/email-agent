from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from email_article_analyzer.api.status import missing_essential_providers
from email_article_analyzer.api.status import provider_status
from email_article_analyzer.model_defaults import DEFAULT_EXTRACTION_MODEL
from email_article_analyzer.model_defaults import DEFAULT_SUMMARY_MODEL
from email_article_analyzer.model_defaults import normalize_model_name
from email_article_analyzer.repositories import RunRepository

router = APIRouter(prefix="/api/runs", tags=["runs"])


class CreateRunRequest(BaseModel):
    extraction_model: str | None = None
    summary_model: str | None = None

    @field_validator("extraction_model", "summary_model", mode="before")
    @classmethod
    def validate_model_name(cls, value: object) -> object:
        if value is None or isinstance(value, str):
            return value
        raise ValueError("model name must be a string")


@router.post("")
def create_run(payload: CreateRunRequest, request: Request) -> dict[str, Any]:
    readiness = provider_status(request.app.state.config)
    missing_providers = missing_essential_providers(readiness)
    if missing_providers:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Essential providers are not ready",
                "missing_essential_providers": missing_providers,
                "provider_status": readiness,
            },
        )
    orchestrator = getattr(request.app.state, "run_orchestrator", None)
    if orchestrator is None:
        raise HTTPException(
            status_code=503,
            detail="Run orchestrator is not configured",
        )
    try:
        extraction_model = normalize_model_name(
            payload.extraction_model,
            DEFAULT_EXTRACTION_MODEL,
        )
        summary_model = normalize_model_name(
            payload.summary_model,
            DEFAULT_SUMMARY_MODEL,
        )
        result = orchestrator.start_discovery_run(
            extraction_model=extraction_model,
            summary_model=summary_model,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Discovery run failed",
                "error": str(exc),
            },
        ) from exc
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
