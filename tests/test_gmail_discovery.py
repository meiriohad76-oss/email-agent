from dataclasses import dataclass

from email_article_analyzer.gmail import GmailDiscoveryService, GmailMessage
from email_article_analyzer.sources import TRUSTED_SOURCES


@dataclass
class FakeGmailProvider:
    messages: list[GmailMessage]
    added_labels: list[tuple[str, str]]
    removed_labels: list[tuple[str, str]]
    marked_read: list[str]

    def search_unread_messages(self, query: str) -> list[GmailMessage]:
        return self.messages

    def add_label(self, message_id: str, label: str) -> None:
        self.added_labels.append((message_id, label))

    def remove_label(self, message_id: str, label: str) -> None:
        self.removed_labels.append((message_id, label))

    def mark_read(self, message_id: str) -> None:
        self.marked_read.append(message_id)


def test_discover_candidates_skips_non_trusted_and_already_analyzed_messages():
    provider = FakeGmailProvider(
        messages=[
            GmailMessage(
                "1",
                "thread-1",
                "alerts@seekingalpha.com",
                "SA",
                [],
                "<h1><a href='https://seekingalpha.com/article/1'>A</a></h1>",
                "",
            ),
            GmailMessage(
                "2",
                "thread-2",
                "person@example.com",
                "Noise",
                [],
                "<a href='https://example.com'>x</a>",
                "",
            ),
            GmailMessage(
                "3",
                "thread-3",
                "newsletter@zacks.com",
                "Done",
                ["Analyzed"],
                "<a href='https://www.zacks.com/stock/news/1'>Z</a>",
                "",
            ),
        ],
        added_labels=[],
        removed_labels=[],
        marked_read=[],
    )
    service = GmailDiscoveryService(provider=provider, sources=TRUSTED_SOURCES)

    candidates = service.discover_candidates()

    assert [candidate.message.message_id for candidate in candidates] == ["1"]
    assert candidates[0].source.source_key == "seeking_alpha"
    assert candidates[0].headline_link.url == "https://seekingalpha.com/article/1"


def test_discover_candidates_returns_valid_articles_newest_first():
    provider = FakeGmailProvider(
        messages=[
            GmailMessage(
                "old",
                "thread-old",
                "alerts@seekingalpha.com",
                "Old",
                [],
                "<h1><a href='https://seekingalpha.com/article/1-old'>Old</a></h1>",
                "",
                internal_date_ms=100,
            ),
            GmailMessage(
                "new",
                "thread-new",
                "alerts@seekingalpha.com",
                "New",
                [],
                "<h1><a href='https://seekingalpha.com/article/2-new'>New</a></h1>",
                "",
                internal_date_ms=200,
            ),
            GmailMessage(
                "newer-invalid",
                "thread-newer-invalid",
                "alerts@seekingalpha.com",
                "Newer invalid",
                [],
                "<a href='https://seekingalpha.com/account/portfolio/all/holdings'>Portfolio</a>",
                "",
                internal_date_ms=300,
            ),
        ],
        added_labels=[],
        removed_labels=[],
        marked_read=[],
    )
    service = GmailDiscoveryService(provider=provider, sources=TRUSTED_SOURCES)

    candidates = service.discover_candidates()

    assert [candidate.message.message_id for candidate in candidates] == ["new", "old"]


def test_mark_success_marks_read_applies_analyzed_and_removes_failed():
    provider = FakeGmailProvider(messages=[], added_labels=[], removed_labels=[], marked_read=[])
    service = GmailDiscoveryService(provider=provider, sources=TRUSTED_SOURCES)

    service.mark_success("msg-1")

    assert provider.marked_read == ["msg-1"]
    assert provider.added_labels == [("msg-1", "Analyzed")]
    assert provider.removed_labels == [("msg-1", "Analysis Failed")]


def test_mark_failure_keeps_unread_and_applies_failed_label():
    provider = FakeGmailProvider(messages=[], added_labels=[], removed_labels=[], marked_read=[])
    service = GmailDiscoveryService(provider=provider, sources=TRUSTED_SOURCES)

    service.mark_failure("msg-1")

    assert provider.marked_read == []
    assert provider.added_labels == [("msg-1", "Analysis Failed")]
