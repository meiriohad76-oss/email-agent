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
        )


def _read_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}
