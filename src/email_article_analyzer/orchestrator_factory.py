from pathlib import Path
import os
import ssl
import tempfile
from typing import Callable

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import httpx

from email_article_analyzer.auth import GMAIL_SCOPES
from email_article_analyzer.article_analysis import OpenAIArticleAnalyzer
from email_article_analyzer.article_analysis import OpenAIArticlePrechecker
from email_article_analyzer.article_analysis import OpenAIRunReportSynthesizer
from email_article_analyzer.article_content import (
    ArticleContentFetcher,
    BrowserExtensionArticleContentFetcher,
    HybridArticleContentFetcher,
    UserChromeArticleContentFetcher,
)
from email_article_analyzer.config import AppConfig
from email_article_analyzer.gmail import GmailDiscoveryService
from email_article_analyzer.providers.gmail_api import GmailApiProvider
from email_article_analyzer.providers.polygon import PolygonHttpClient
from email_article_analyzer.rating_enrichment import TickerRatingEnrichmentService
from email_article_analyzer.repositories import GmailDiscoveryRepository
from email_article_analyzer.repositories import RunRepository
from email_article_analyzer.run_orchestration import RunOrchestrator
from email_article_analyzer.source_login_browser import create_article_chrome_ready_launcher
from email_article_analyzer.sources import TRUSTED_SOURCES


def create_run_orchestrator(
    config: AppConfig,
    database_path: str,
    credentials_cls=Credentials,
    service_builder: Callable | None = None,
    openai_client_factory: Callable | None = None,
    source_browser_session=None,
    browser_task_queue=None,
    run_control=None,
) -> RunOrchestrator | None:
    provider = create_gmail_provider(
        config=config,
        credentials_cls=credentials_cls,
        service_builder=service_builder,
    )
    if provider is None:
        return None
    discovery_service = GmailDiscoveryService(
        provider=provider,
        sources=TRUSTED_SOURCES,
    )
    article_analyzer = None
    article_prechecker = None
    article_content_fetcher = None
    report_synthesizer = None
    if config.openai_api_key:
        if openai_client_factory is None:
            client = _create_openai_client(
                config.openai_api_key,
                tls_verify=config.tls_verify,
            )
        else:
            client = openai_client_factory(config.openai_api_key)
        if os.getenv("APP_OPENAI_USAGE_LOG", "1") == "1" and hasattr(client, "responses"):
            from email_article_analyzer.usage_logging import UsageLoggingClient
            client = UsageLoggingClient(client, config.database_path)
        article_analyzer = OpenAIArticleAnalyzer(
            client=client,
        )
        article_prechecker = OpenAIArticlePrechecker(
            client=client,
        )
        if os.getenv("APP_ARTICLE_ROUTING", "local_first") == "local_first":
            # Cost control: local model for every article, OpenAI only for articles about holdings.
            # The OpenAI precheck is dropped (it marked 1046/1047 articles relevant and gated nothing).
            from email_article_analyzer.local_routing import LocalFirstArticleAnalyzer, OllamaArticleAnalyzer, file_tickers
            from email_article_analyzer.run_orchestration import _active_watchlist_tickers
            article_analyzer = LocalFirstArticleAnalyzer(
                local=OllamaArticleAnalyzer(
                    base_url=os.getenv("APP_OLLAMA_URL", "http://127.0.0.1:11434"),
                    model=os.getenv("APP_LOCAL_ARTICLE_MODEL", "gemma4:12b"),
                ),
                cloud=article_analyzer,
                # holdings = the analyzer's own portfolio list PLUS the agency's nightly holdings file (stays exact
                # when Meiri buys/sells: the agency syncs Seeking Alpha every night)
                holdings=(lambda agency_holdings=file_tickers(os.getenv("APP_HOLDINGS_TICKERS_FILE", "~/MeiriServer/Agency/holdings_tickers.txt")):
                          _active_watchlist_tickers(config.database_path) | agency_holdings()),
                watchlist=file_tickers(os.getenv("APP_WATCH_TICKERS_FILE", "~/MeiriServer/Agency/watch_tickers.txt")),
                escalate_below=float(os.getenv("APP_ESCALATE_BELOW", "0.9")),
            )
            article_prechecker = None
        report_synthesizer = OpenAIRunReportSynthesizer(
            client=client,
        )
        article_content_fetcher = _create_article_content_fetcher(
            config=config,
            tls_verify=config.tls_verify,
            source_browser_session=source_browser_session,
            browser_task_queue=browser_task_queue,
            article_page_pause_seconds=config.article_page_pause_seconds,
        )
    run_repository = RunRepository(database_path)
    rating_enricher = (
        TickerRatingEnrichmentService(
            fetcher=article_content_fetcher,
            repository=run_repository,
            polygon_client=PolygonHttpClient(config.polygon_api_key)
            if config.polygon_api_key
            else None,
            include_research=True,
            investing_mapping_path=_resolve_project_path(config.investing_mapping_path),
        )
        if article_content_fetcher is not None
        else None
    )
    return RunOrchestrator(
        run_repository=run_repository,
        gmail_repository=GmailDiscoveryRepository(database_path),
        discovery_service=discovery_service,
        article_analyzer=article_analyzer,
        article_prechecker=article_prechecker,
        article_content_fetcher=article_content_fetcher,
        report_synthesizer=report_synthesizer,
        rating_enricher=rating_enricher,
        stop_requested=run_control.is_stop_requested if run_control is not None else None,
        gmail_mark_timeout_seconds=config.gmail_api_timeout_seconds + 5.0,
    )


def create_gmail_provider(
    config: AppConfig,
    credentials_cls=Credentials,
    service_builder: Callable | None = None,
) -> GmailApiProvider | None:
    if not Path(config.gmail_token_path).exists():
        return None
    credentials = credentials_cls.from_authorized_user_file(
        config.gmail_token_path,
        GMAIL_SCOPES,
    )
    if service_builder is None:
        service = _build_gmail_service(
            credentials,
            timeout_seconds=config.gmail_api_timeout_seconds,
        )
    else:
        service = service_builder("gmail", "v1", credentials=credentials)
    return GmailApiProvider(service=service)


def _create_openai_client(
    api_key: str,
    openai_cls=None,
    http_client_cls=httpx.Client,
    ca_bundle_path: str | None = None,
    tls_verify: bool = True,
):
    if openai_cls is None:
        from openai import OpenAI

        openai_cls = OpenAI

    verify = ca_bundle_path or _default_ca_bundle_path()
    http_client = http_client_cls(verify=verify if tls_verify else False)
    return openai_cls(api_key=api_key, http_client=http_client)


def _create_article_content_fetcher(
    config: AppConfig | None = None,
    http_client_cls=httpx.Client,
    ca_bundle_path: str | None = None,
    tls_verify: bool = True,
    source_browser_session=None,
    browser_task_queue=None,
    article_page_pause_seconds: float = 6.0,
) -> ArticleContentFetcher:
    verify = ca_bundle_path or _default_ca_bundle_path()
    http_fetcher = ArticleContentFetcher(
        http_client=http_client_cls(verify=verify if tls_verify else False)
    )
    if browser_task_queue is not None:
        browser_fetcher = BrowserExtensionArticleContentFetcher(
            browser_task_queue=browser_task_queue,
            page_pause_seconds=article_page_pause_seconds,
        )
    else:
        browser_fetcher = UserChromeArticleContentFetcher(
            chrome_launcher=create_article_chrome_ready_launcher(
                profile_path=(
                    config.article_chrome_profile_path
                    if config is not None
                    else "data/user-chrome-profile"
                ),
                mode=config.article_chrome_mode if config is not None else "app_profile",
                cdp_url=(
                    config.article_chrome_cdp_url
                    if config is not None
                    else "http://127.0.0.1:9222"
                ),
            ),
            cdp_url=(
                config.article_chrome_cdp_url
                if config is not None
                else "http://127.0.0.1:9222"
            ),
            page_pause_seconds=article_page_pause_seconds,
        )
    return HybridArticleContentFetcher(
        http_fetcher=http_fetcher,
        browser_fetcher=browser_fetcher,
        browser_domains=("seekingalpha.com", "zacks.com", "investing.com"),
    )


def _build_gmail_service(
    credentials,
    api_builder: Callable = build,
    http_cls=None,
    authorized_http_cls=None,
    ca_bundle_path: str | None = None,
    timeout_seconds: float = 20.0,
):
    import certifi
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp

    http_factory = http_cls or httplib2.Http
    authorized_http_factory = authorized_http_cls or AuthorizedHttp
    ca_certs = ca_bundle_path or _default_ca_bundle_path()
    http = http_factory(ca_certs=ca_certs, timeout=timeout_seconds)
    authorized_http = authorized_http_factory(credentials, http=http)
    return api_builder("gmail", "v1", http=authorized_http)


def _default_ca_bundle_path() -> str:
    import certifi

    return _build_ca_bundle(certifi_bundle_path=certifi.where())


def _resolve_project_path(value: str) -> str:
    path = Path(value).expanduser()
    if path.is_absolute():
        return str(path)
    project_root = Path(__file__).resolve().parents[2]
    return str((project_root / path).resolve())


def _build_ca_bundle(
    certifi_bundle_path: str,
    output_path: Path | None = None,
    windows_certificates=None,
    der_to_pem: Callable[[bytes], str] = ssl.DER_cert_to_PEM_cert,
) -> str:
    if os.name != "nt" and windows_certificates is None:
        return certifi_bundle_path

    certificates = (
        windows_certificates
        if windows_certificates is not None
        else ssl.enum_certificates("ROOT")
    )
    output = output_path or Path(tempfile.gettempdir()) / "email_article_analyzer_ca_bundle.pem"
    output.write_bytes(Path(certifi_bundle_path).read_bytes())
    with output.open("ab") as bundle:
        for certificate, encoding, _trust in certificates:
            if encoding != "x509_asn":
                continue
            bundle.write(der_to_pem(certificate).encode("ascii"))
    return str(output)
