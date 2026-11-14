from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class AppConfig:
    database_path: str
    dashboard_password: str
    polygon_api_key: str | None
    openai_api_key: str | None
    gmail_credentials_path: str
    gmail_token_path: str
    tls_verify: bool = True
    source_login_confirmation_path: str = "data/source_login_confirmed.json"
    article_page_pause_seconds: float = 6.0
    article_chrome_mode: str = "app_profile"
    article_chrome_profile_path: str = "data/user-chrome-profile"
    article_chrome_cdp_url: str = "http://127.0.0.1:9222"
    gmail_api_timeout_seconds: float = 20.0
    investing_mapping_path: str = "data/investing_instrument_mapping.csv"

    @classmethod
    def from_env(cls) -> "AppConfig":
        load_dotenv(dotenv_path=Path.cwd() / ".env")
        polygon_key = os.getenv("POLYGON_API_KEY") or None
        openai_key = os.getenv("OPENAI_API_KEY") or None
        return cls(
            database_path=os.getenv("APP_DATABASE_PATH", "data/app.db"),
            dashboard_password=os.getenv("APP_DASHBOARD_PASSWORD", "change-me"),
            polygon_api_key=polygon_key,
            openai_api_key=openai_key,
            gmail_credentials_path=os.getenv(
                "GMAIL_CREDENTIALS_PATH",
                "config/gmail_credentials.json",
            ),
            gmail_token_path=os.getenv("GMAIL_TOKEN_PATH", "data/gmail_token.json"),
            tls_verify=_read_bool_env("TLS_VERIFY", default=True),
            source_login_confirmation_path=os.getenv(
                "SOURCE_LOGIN_CONFIRMATION_PATH",
                "data/source_login_confirmed.json",
            ),
            article_page_pause_seconds=_read_float_env(
                "ARTICLE_PAGE_PAUSE_SECONDS",
                default=6.0,
            ),
            article_chrome_mode=_read_choice_env(
                "ARTICLE_CHROME_MODE",
                default="app_profile",
                choices={"app_profile", "existing_debug"},
            ),
            article_chrome_profile_path=os.getenv(
                "ARTICLE_CHROME_PROFILE_PATH",
                "data/user-chrome-profile",
            ),
            article_chrome_cdp_url=os.getenv(
                "ARTICLE_CHROME_CDP_URL",
                "http://127.0.0.1:9222",
            ),
            gmail_api_timeout_seconds=_read_float_env(
                "GMAIL_API_TIMEOUT_SECONDS",
                default=20.0,
            ),
            investing_mapping_path=os.getenv(
                "INVESTING_MAPPING_PATH",
                "data/investing_instrument_mapping.csv",
            ),
        )


def _read_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _read_float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _read_choice_env(name: str, default: str, choices: set[str]) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    return normalized if normalized in choices else default
