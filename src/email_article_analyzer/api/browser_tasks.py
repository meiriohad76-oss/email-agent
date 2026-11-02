from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from email_article_analyzer.browser_tasks import BrowserArticleTaskResult
from email_article_analyzer.rating_enrichment import (
    parse_seeking_alpha_ratings,
    parse_zacks_ratings,
)

router = APIRouter(prefix="/api/browser-tasks", tags=["browser-tasks"])


class CompleteBrowserTaskRequest(BaseModel):
    task_id: str
    status: str
    final_url: str | None = None
    title: str | None = None
    extracted_text: str | None = None
    http_status: int | None = None
    error: str | None = None


class TestExtractBrowserTaskRequest(BaseModel):
    url: str
    timeout_seconds: float = 120.0
    ticker: str | None = None
    include_full_text: bool = False


@router.get("/status")
def browser_task_status(request: Request) -> dict[str, Any]:
    queue = request.app.state.browser_task_queue
    return {
        "status": "connected" if queue.is_extension_connected() else "not_connected",
    }


@router.get("/next")
def next_browser_task(request: Request) -> dict[str, Any]:
    queue = request.app.state.browser_task_queue
    task = queue.next_task()
    if task is None:
        return {"status": "idle"}
    return {
        "status": "task",
        "task_id": task.task_id,
        "url": task.url,
    }


@router.post("/complete")
def complete_browser_task(
    payload: CompleteBrowserTaskRequest,
    request: Request,
) -> dict[str, str]:
    queue = request.app.state.browser_task_queue
    accepted = queue.complete_task(
        BrowserArticleTaskResult(
            task_id=payload.task_id,
            status=payload.status,
            final_url=payload.final_url,
            title=payload.title,
            extracted_text=payload.extracted_text,
            http_status=payload.http_status,
            error=payload.error,
        )
    )
    if not accepted:
        return {"status": "rejected", "reason": "unknown_or_expired_task"}
    return {"status": "accepted"}


@router.post("/test-extract")
def test_extract_browser_task(
    payload: TestExtractBrowserTaskRequest,
    request: Request,
) -> dict[str, Any]:
    queue = request.app.state.browser_task_queue
    result = queue.submit_article_task(
        payload.url,
        timeout_seconds=payload.timeout_seconds,
    )
    text = result.extracted_text or ""
    parsed_sa_snapshots: list[dict[str, Any]] = []
    parsed_zacks_snapshots: list[dict[str, Any]] = []
    if "seekingalpha.com/symbol/" in (result.final_url or payload.url) and payload.ticker:
        parsed_sa_snapshots = parse_seeking_alpha_ratings(payload.ticker, text)
    if "zacks.com/stock/" in (result.final_url or payload.url) and payload.ticker:
        parsed_zacks_snapshots = parse_zacks_ratings(payload.ticker, text)
    payload_data = {
        "status": result.status,
        "final_url": result.final_url,
        "title": result.title,
        "http_status": result.http_status,
        "error": result.error,
        "text_char_count": len(text),
        "text_preview": text[:2000],
        "has_sa_data": "SA_DATA" in text,
        "parsed_seeking_alpha_snapshots": parsed_sa_snapshots,
        "parsed_zacks_snapshots": parsed_zacks_snapshots,
    }
    if payload.include_full_text:
        payload_data["extracted_text"] = text
    return payload_data
