from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from email_article_analyzer.config import AppConfig

router = APIRouter(prefix="/api/status", tags=["status"])


def _provider(status: str, details: list[str]) -> dict[str, Any]:
    return {"status": status, "details": details}


def _ready_if_present(value: str | None, missing_message: str) -> dict[str, Any]:
    if value:
        return _provider("ready", [])
    return _provider("missing", [missing_message])


def provider_status(config: AppConfig) -> dict[str, Any]:
    credentials_exists = Path(config.gmail_credentials_path).exists()
    token_exists = Path(config.gmail_token_path).exists()
    gmail_details = []
    if not credentials_exists:
        gmail_details.append("Gmail credentials file is missing")
    if not token_exists:
        gmail_details.append("Gmail token file is missing")

    providers = {
        "openai": _ready_if_present(config.openai_api_key, "OPENAI_API_KEY is missing"),
        "polygon": _ready_if_present(config.polygon_api_key, "POLYGON_API_KEY is missing"),
        "gmail": _provider("ready" if not gmail_details else "action_required", gmail_details),
        "source_logins": _provider(
            "action_required",
            ["Confirm premium source logins are available before running article extraction"],
        ),
    }
    overall_status = "ready"
    if any(provider["status"] != "ready" for provider in providers.values()):
        overall_status = "action_required"
    return {"overall_status": overall_status, "providers": providers}


@router.get("/providers")
def get_provider_status(request: Request) -> dict[str, Any]:
    config = getattr(request.app.state, "config", AppConfig.from_env())
    return provider_status(config)
