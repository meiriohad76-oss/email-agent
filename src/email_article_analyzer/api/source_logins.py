from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from email_article_analyzer.source_logins import SourceLoginStore

router = APIRouter(prefix="/api/source-logins", tags=["source-logins"])


class ConfirmSourceLoginsRequest(BaseModel):
    sources: list[str] = ["seeking_alpha"]


class OpenSourceLoginRequest(BaseModel):
    source: str = "seeking_alpha"


SOURCE_LOGIN_URLS = {
    "seeking_alpha": "https://seekingalpha.com/",
}


@router.post("/open")
def open_source_login(
    payload: OpenSourceLoginRequest,
    request: Request,
) -> dict[str, Any]:
    url = SOURCE_LOGIN_URLS.get(payload.source)
    if url is None:
        return {
            "status": "unsupported",
            "source": payload.source,
            "url": None,
        }
    request.app.state.source_browser_session.open_login_page(url)
    return {
        "status": "opened",
        "source": payload.source,
        "url": url,
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
