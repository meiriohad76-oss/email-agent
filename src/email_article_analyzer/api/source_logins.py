from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from email_article_analyzer.source_logins import SourceLoginStore

router = APIRouter(prefix="/api/source-logins", tags=["source-logins"])


class ConfirmSourceLoginsRequest(BaseModel):
    sources: list[str] = ["seeking_alpha"]


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
