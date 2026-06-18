from pathlib import Path
from typing import Callable

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from email_article_analyzer.auth import GMAIL_SCOPES
from email_article_analyzer.article_analysis import OpenAIArticleAnalyzer
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
    service_builder: Callable = build,
    openai_client_factory: Callable | None = None,
) -> RunOrchestrator | None:
    if not Path(config.gmail_token_path).exists():
        return None
    credentials = credentials_cls.from_authorized_user_file(
        config.gmail_token_path,
        GMAIL_SCOPES,
    )
    service = service_builder("gmail", "v1", credentials=credentials)
    provider = GmailApiProvider(service=service)
    discovery_service = GmailDiscoveryService(
        provider=provider,
        sources=TRUSTED_SOURCES,
    )
    article_analyzer = None
    if config.openai_api_key:
        client_factory = openai_client_factory or _create_openai_client
        article_analyzer = OpenAIArticleAnalyzer(
            client=client_factory(config.openai_api_key),
        )
    return RunOrchestrator(
        run_repository=RunRepository(database_path),
        gmail_repository=GmailDiscoveryRepository(database_path),
        discovery_service=discovery_service,
        article_analyzer=article_analyzer,
    )


def _create_openai_client(api_key: str):
    from openai import OpenAI

    return OpenAI(api_key=api_key)
