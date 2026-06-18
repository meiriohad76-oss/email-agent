from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from email_article_analyzer.config import AppConfig

router = APIRouter(prefix="/api/status", tags=["status"])


def _provider(
    status: str,
    details: list[str],
    setup_steps: list[str] | None = None,
) -> dict[str, Any]:
    return {"status": status, "details": details, "setup_steps": setup_steps or []}


def _ready_if_present(
    value: str | None,
    missing_message: str,
    setup_step: str,
) -> dict[str, Any]:
    if value:
        return _provider("ready", [])
    return _provider("missing", [missing_message], [setup_step])


def provider_status(config: AppConfig) -> dict[str, Any]:
    credentials_exists = Path(config.gmail_credentials_path).exists()
    token_exists = Path(config.gmail_token_path).exists()
    gmail_details = []
    if not credentials_exists:
        gmail_details.append("Gmail credentials file is missing")
    if not token_exists:
        gmail_details.append("Gmail token file is missing")

    providers = {
        "openai": _ready_if_present(
            config.openai_api_key,
            "OPENAI_API_KEY is missing",
            "Set OPENAI_API_KEY in the environment or .env file",
        ),
        "polygon": _ready_if_present(
            config.polygon_api_key,
            "POLYGON_API_KEY is missing",
            "Set POLYGON_API_KEY in the environment or .env file",
        ),
        "gmail": _provider(
            "ready" if not gmail_details else "action_required",
            gmail_details,
            [
                f"Place Gmail OAuth client credentials at {config.gmail_credentials_path}",
                f"Complete Gmail OAuth and save token at {config.gmail_token_path}",
            ]
            if gmail_details
            else [],
        ),
        "source_logins": _provider(
            "action_required",
            ["Confirm premium source logins are available before running article extraction"],
            ["Confirm source website sessions before extraction"],
        ),
    }
    overall_status = "ready"
    if any(provider["status"] != "ready" for provider in providers.values()):
        overall_status = "action_required"
    return {"overall_status": overall_status, "providers": providers}


def missing_essential_providers(status_payload: dict[str, Any]) -> list[str]:
    providers = status_payload.get("providers", {})
    return [
        provider_key
        for provider_key in ("openai", "gmail")
        if providers.get(provider_key, {}).get("status") != "ready"
    ]


@router.get("/providers")
def get_provider_status(request: Request) -> dict[str, Any]:
    config = getattr(request.app.state, "config", AppConfig.from_env())
    return provider_status(config)
