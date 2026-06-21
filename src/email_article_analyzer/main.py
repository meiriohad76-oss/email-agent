from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from email_article_analyzer.api.dashboard import STATIC_DIR
from email_article_analyzer.api.dashboard import router as dashboard_router
from email_article_analyzer.api.health import router as health_router
from email_article_analyzer.api.runs import router as runs_router
from email_article_analyzer.api.source_logins import router as source_logins_router
from email_article_analyzer.api.status import router as status_router
from email_article_analyzer.api.watchlist import router as watchlist_router
from email_article_analyzer.article_content import PersistentBrowserSession
from email_article_analyzer.config import AppConfig
from email_article_analyzer.db import initialize_database
from email_article_analyzer.orchestrator_factory import create_run_orchestrator


def create_app(database_path: str | None = None, run_orchestrator=None) -> FastAPI:
    config = AppConfig.from_env()
    resolved_database_path = database_path or config.database_path
    initialize_database(resolved_database_path)

    app = FastAPI(title="Email Article Analyzer")
    app.state.config = config
    app.state.database_path = resolved_database_path
    app.state.source_browser_session = PersistentBrowserSession()
    app.state.run_orchestrator = run_orchestrator
    if app.state.run_orchestrator is None:
        app.state.run_orchestrator = create_run_orchestrator(
            config,
            resolved_database_path,
            source_browser_session=app.state.source_browser_session,
        )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(dashboard_router)
    app.include_router(health_router)
    app.include_router(source_logins_router)
    app.include_router(status_router)
    app.include_router(runs_router)
    app.include_router(watchlist_router)
    return app


app = create_app()
