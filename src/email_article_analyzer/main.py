from fastapi import FastAPI

from email_article_analyzer.api.health import router as health_router
from email_article_analyzer.config import AppConfig
from email_article_analyzer.db import initialize_database


def create_app(database_path: str | None = None) -> FastAPI:
    config = AppConfig.from_env()
    resolved_database_path = database_path or config.database_path
    initialize_database(resolved_database_path)

    app = FastAPI(title="Email Article Analyzer")
    app.state.database_path = resolved_database_path
    app.include_router(health_router)
    return app


app = create_app()
