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
from email_article_analyzer.article_content import (
    ArticleContentFetcher,
    BrowserArticleContentFetcher,
    HybridArticleContentFetcher,
)
from email_article_analyzer.config import AppConfig
from email_article_analyzer.gmail import GmailDiscoveryService
from email_article_analyzer.providers.gmail_api import GmailApiProvider
from email_article_analyzer.repositories import GmailDiscoveryRepository
from email_article_analyzer.repositories import RunRepository
from email_article_analyzer.run_orchestration import RunOrchestrator
from email_article_analyzer.sources import TRUSTED_SOURCES


def create_run_orchestrator(
    config: AppConfig,
    database_path: str,
    credentials_cls=Credentials,
    service_builder: Callable | None = None,
    openai_client_factory: Callable | None = None,
    source_browser_session=None,
    run_control=None,
) -> RunOrchestrator | None:
    if not Path(config.gmail_token_path).exists():
        return None
    credentials = credentials_cls.from_authorized_user_file(
        config.gmail_token_path,
        GMAIL_SCOPES,
    )
    if service_builder is None:
        service = _build_gmail_service(credentials)
    else:
        service = service_builder("gmail", "v1", credentials=credentials)
    provider = GmailApiProvider(service=service)
    discovery_service = GmailDiscoveryService(
        provider=provider,
        sources=TRUSTED_SOURCES,
    )
    article_analyzer = None
    article_content_fetcher = None
    if config.openai_api_key:
        if openai_client_factory is None:
            client = _create_openai_client(
                config.openai_api_key,
                tls_verify=config.tls_verify,
            )
        else:
            client = openai_client_factory(config.openai_api_key)
        article_analyzer = OpenAIArticleAnalyzer(
            client=client,
        )
        article_content_fetcher = _create_article_content_fetcher(
            tls_verify=config.tls_verify,
            source_browser_session=source_browser_session,
        )
    return RunOrchestrator(
        run_repository=RunRepository(database_path),
        gmail_repository=GmailDiscoveryRepository(database_path),
        discovery_service=discovery_service,
        article_analyzer=article_analyzer,
        article_content_fetcher=article_content_fetcher,
        stop_requested=run_control.is_stop_requested if run_control is not None else None,
    )


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
    http_client_cls=httpx.Client,
    ca_bundle_path: str | None = None,
    tls_verify: bool = True,
    source_browser_session=None,
) -> ArticleContentFetcher:
    verify = ca_bundle_path or _default_ca_bundle_path()
    http_fetcher = ArticleContentFetcher(
        http_client=http_client_cls(verify=verify if tls_verify else False)
    )
    browser_fetcher = BrowserArticleContentFetcher(
        browser_session=source_browser_session,
    )
    return HybridArticleContentFetcher(
        http_fetcher=http_fetcher,
        browser_fetcher=browser_fetcher,
        browser_domains=("seekingalpha.com",),
    )


def _build_gmail_service(
    credentials,
    api_builder: Callable = build,
    http_cls=None,
    authorized_http_cls=None,
    ca_bundle_path: str | None = None,
):
    import certifi
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp

    http_factory = http_cls or httplib2.Http
    authorized_http_factory = authorized_http_cls or AuthorizedHttp
    ca_certs = ca_bundle_path or _default_ca_bundle_path()
    http = http_factory(ca_certs=ca_certs)
    authorized_http = authorized_http_factory(credentials, http=http)
    return api_builder("gmail", "v1", http=authorized_http)


def _default_ca_bundle_path() -> str:
    import certifi

    return _build_ca_bundle(certifi_bundle_path=certifi.where())


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
