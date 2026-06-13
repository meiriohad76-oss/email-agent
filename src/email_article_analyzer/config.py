from dataclasses import dataclass
import os


@dataclass(frozen=True)
class AppConfig:
    database_path: str
    dashboard_password: str
    polygon_api_key: str | None

    @classmethod
    def from_env(cls) -> "AppConfig":
        polygon_key = os.getenv("POLYGON_API_KEY") or None
        return cls(
            database_path=os.getenv("APP_DATABASE_PATH", "data/app.db"),
            dashboard_password=os.getenv("APP_DASHBOARD_PASSWORD", "change-me"),
            polygon_api_key=polygon_key,
        )
