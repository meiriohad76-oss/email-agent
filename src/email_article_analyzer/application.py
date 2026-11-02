import base64
from pathlib import Path
import secrets

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from email_article_analyzer.api.browser_tasks import router as browser_tasks_router
from email_article_analyzer.api.dashboard import STATIC_DIR
from email_article_analyzer.api.dashboard import router as dashboard_router
from email_article_analyzer.api.health import router as health_router
from email_article_analyzer.api.runs import router as runs_router
from email_article_analyzer.api.research import router as research_router
from email_article_analyzer.api.source_logins import router as source_logins_router
from email_article_analyzer.api.status import router as status_router
from email_article_analyzer.api.watchlist import router as watchlist_router
from email_article_analyzer.article_content import PersistentBrowserSession
from email_article_analyzer.browser_tasks import BrowserTaskQueue
from email_article_analyzer.config import AppConfig
from email_article_analyzer.db import initialize_database
from email_article_analyzer.orchestrator_factory import create_run_orchestrator
from email_article_analyzer.research_extraction import BulkResearchExtractionManager
from email_article_analyzer.run_control import RunControl
from email_article_analyzer.source_login_browser import create_article_chrome_launcher


def create_app(database_path: str | None = None, run_orchestrator=None) -> FastAPI:
    config = AppConfig.from_env()
    resolved_database_path = database_path or config.database_path
    initialize_database(resolved_database_path)

    app = FastAPI(title="Email Article Analyzer")
    app.state.config = config
    app.state.database_path = resolved_database_path
    app.state.research_universe_path = (
        Path(resolved_database_path).resolve().parent / "research_universe_120.csv"
    )
    app.state.research_scoring_config_path = (
        Path(resolved_database_path).resolve().parent / "research_scoring_config.json"
    )
    app.state.source_browser_session = PersistentBrowserSession()
    app.state.browser_task_queue = BrowserTaskQueue()
    app.state.source_login_launcher = create_article_chrome_launcher(
        profile_path=config.article_chrome_profile_path,
        mode=config.article_chrome_mode,
        cdp_url=config.article_chrome_cdp_url,
    )
    app.state.run_control = RunControl()
    app.state.bulk_research_extraction = BulkResearchExtractionManager()
    app.state.run_orchestrator = run_orchestrator
    app.state.browser_bridge_required_for_runs = run_orchestrator is None
    _install_password_auth(app, config)
    if app.state.run_orchestrator is None:
        app.state.run_orchestrator = create_run_orchestrator(
            config,
            resolved_database_path,
            source_browser_session=app.state.source_browser_session,
            browser_task_queue=app.state.browser_task_queue,
            run_control=app.state.run_control,
        )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(dashboard_router)
    app.include_router(health_router)
    app.include_router(browser_tasks_router)
    app.include_router(source_logins_router)
    app.include_router(status_router)
    app.include_router(runs_router)
    app.include_router(research_router)
    app.include_router(watchlist_router)
    return app


def _install_password_auth(app: FastAPI, config: AppConfig) -> None:
    password = config.dashboard_password

    @app.middleware("http")
    async def require_dashboard_password(request: Request, call_next):
        if request.url.path == "/api/health":
            return await call_next(request)
        if not password or password == "change-me":
            if _is_loopback_request(request):
                return await call_next(request)
            return Response(
                content=(
                    "Set APP_DASHBOARD_PASSWORD before exposing the dashboard "
                    "outside localhost."
                ),
                status_code=503,
            )
        if _request_has_password(request, password):
            return await call_next(request)
        return Response(
            content="Authentication required",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Email Article Analyzer"'},
        )


def _request_has_password(request: Request, password: str) -> bool:
    header_password = request.headers.get("x-email-article-analyzer-password")
    if header_password and secrets.compare_digest(header_password, password):
        return True
    authorization = request.headers.get("authorization") or ""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "basic" or not token:
        return False
    try:
        decoded = base64.b64decode(token).decode("utf-8")
    except Exception:
        return False
    _username, separator, supplied_password = decoded.partition(":")
    return bool(separator) and secrets.compare_digest(supplied_password, password)


def _is_loopback_request(request: Request) -> bool:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        host = forwarded_for.split(",", 1)[0].strip()
    else:
        host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}
