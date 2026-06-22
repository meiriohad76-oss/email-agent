from dataclasses import dataclass
from typing import Protocol

from email_article_analyzer.link_extraction import ExtractedLink, extract_headline_link
from email_article_analyzer.sources import TrustedSource, match_source_for_sender

ANALYZED_LABEL = "Analyzed"
FAILED_LABEL = "Analysis Failed"
DISCOVERY_SCAN_LIMIT = 100


@dataclass(frozen=True)
class GmailMessage:
    message_id: str
    thread_id: str
    sender: str
    subject: str
    labels: list[str]
    html_body: str
    text_body: str
    internal_date_ms: int = 0


@dataclass(frozen=True)
class GmailCandidate:
    message: GmailMessage
    source: TrustedSource
    headline_link: ExtractedLink


class GmailProvider(Protocol):
    def search_unread_messages(
        self,
        query: str,
        max_results: int | None = None,
    ) -> list[GmailMessage]:
        ...

    def iter_unread_messages(
        self,
        query: str,
        max_results: int | None = None,
        page_size: int = 10,
    ):
        ...

    def add_label(self, message_id: str, label: str) -> None:
        ...

    def remove_label(self, message_id: str, label: str) -> None:
        ...

    def mark_read(self, message_id: str) -> None:
        ...


def build_unread_trusted_query(sources: tuple[TrustedSource, ...]) -> str:
    senders = sorted({domain for source in sources for domain in source.sender_domains})
    sender_clause = " OR ".join(f"from:{domain}" for domain in senders)
    return f"is:unread -label:{ANALYZED_LABEL} ({sender_clause})"


class GmailDiscoveryService:
    def __init__(self, provider: GmailProvider, sources: tuple[TrustedSource, ...]):
        self.provider = provider
        self.sources = sources

    def discover_candidates(self) -> list[GmailCandidate]:
        return list(self.iter_candidates())

    def iter_candidates(self):
        query = build_unread_trusted_query(self.sources)
        message_iterator = getattr(self.provider, "iter_unread_messages", None)
        if message_iterator is None:
            messages = self.provider.search_unread_messages(
                query,
                max_results=DISCOVERY_SCAN_LIMIT,
            )
            iterable = sorted(messages, key=lambda item: item.internal_date_ms, reverse=True)
        else:
            iterable = message_iterator(
                query,
                max_results=DISCOVERY_SCAN_LIMIT,
                page_size=10,
            )

        for message in iterable:
            if ANALYZED_LABEL in message.labels:
                continue
            source = match_source_for_sender(message.sender)
            if source is None:
                continue
            headline_link = extract_headline_link(
                message.html_body,
                message.text_body,
                source,
            )
            if headline_link is None:
                continue
            yield GmailCandidate(
                message=message,
                source=source,
                headline_link=headline_link,
            )

    def mark_success(self, message_id: str) -> None:
        self.provider.mark_read(message_id)
        self.provider.add_label(message_id, ANALYZED_LABEL)
        self.provider.remove_label(message_id, FAILED_LABEL)

    def mark_failure(self, message_id: str) -> None:
        self.provider.add_label(message_id, FAILED_LABEL)
