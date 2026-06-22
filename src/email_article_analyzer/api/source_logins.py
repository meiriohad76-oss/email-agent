from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from email_article_analyzer.sources import TRUSTED_SOURCES
from email_article_analyzer.source_logins import SourceLoginStore

router = APIRouter(prefix="/api/source-logins", tags=["source-logins"])


class ConfirmSourceLoginsRequest(BaseModel):
    sources: list[str] = ["seeking_alpha", "zacks"]


class OpenSourceLoginRequest(BaseModel):
    source: str = "seeking_alpha"


SOURCE_LOGIN_URLS = {
    "seeking_alpha": "https://seekingalpha.com/",
    "zacks": "https://www.zacks.com/login",
}


@router.post("/open")
def open_source_login(
    payload: OpenSourceLoginRequest,
    request: Request,
) -> dict[str, Any]:
    source_keys = _source_keys_to_open(payload.source)
    if not source_keys:
        return {
            "status": "unsupported",
            "source": payload.source,
            "opened_sources": [],
        }
    opened_sources = []
    launcher = request.app.state.source_login_launcher
    for source_key in source_keys:
        url = SOURCE_LOGIN_URLS[source_key]
        launcher.open_url(url)
        opened_sources.append({"source": source_key, "url": url})
    return {
        "status": "opened",
        "source": payload.source,
        "opened_sources": opened_sources,
    }


@router.post("/confirm")
def confirm_source_logins(
    payload: ConfirmSourceLoginsRequest,
    request: Request,
) -> dict[str, Any]:
    store = SourceLoginStore(request.app.state.config.source_login_confirmation_path)
    confirmation = store.confirm(payload.sources)
    return {
        "status": confirmation.status,
        "sources": confirmation.sources,
    }


def _source_keys_to_open(source: str) -> list[str]:
    if source == "all":
        return [trusted.source_key for trusted in TRUSTED_SOURCES if trusted.source_key in SOURCE_LOGIN_URLS]
    return [source] if source in SOURCE_LOGIN_URLS else []
