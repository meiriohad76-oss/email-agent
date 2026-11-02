from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from email_article_analyzer.sources import TRUSTED_SOURCES
from email_article_analyzer.source_logins import SourceLoginStore

router = APIRouter(prefix="/api/source-logins", tags=["source-logins"])


class ConfirmSourceLoginsRequest(BaseModel):
    sources: list[str] = ["seeking_alpha", "zacks", "investing"]


class OpenSourceLoginRequest(BaseModel):
    source: str = "seeking_alpha"


SOURCE_LOGIN_URLS = {
    "seeking_alpha": "https://seekingalpha.com/",
    "zacks": "https://www.zacks.com/login",
    "investing": "https://www.investing.com/",
}


@router.post("/open")
def open_source_login(
    payload: OpenSourceLoginRequest,
    request: Request,
) -> dict[str, Any]:
    source_keys = _source_keys_to_open(payload.source)
    return {
        "status": "browser_open_required",
        "source": payload.source,
        "opened_sources": [],
        "login_urls": [
            {
                "source": source_key,
                "url": SOURCE_LOGIN_URLS[source_key],
            }
            for source_key in source_keys
        ],
        "message": "Open these URLs from dashboard JavaScript so Chrome creates tabs in the current window.",
    }


@router.get("/urls")
def source_login_urls(source: str = "all") -> dict[str, Any]:
    source_keys = _source_keys_to_open(source)
    return {
        "source": source,
        "login_urls": [
            {
                "source": source_key,
                "url": SOURCE_LOGIN_URLS[source_key],
            }
            for source_key in source_keys
        ],
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
