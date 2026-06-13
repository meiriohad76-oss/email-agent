# Gmail Discovery Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Gmail discovery foundation for the MVP: trusted source matching, unread query construction, candidate filtering, headline-link extraction, and tested label transition orchestration behind a Gmail provider interface.

**Architecture:** Keep Gmail API calls behind a protocol so discovery logic can be tested without live Gmail access. Use stdlib HTML parsing for headline-link detection in this slice; source-specific refinements and real OAuth clients can come later.

**Tech Stack:** Python 3.14-compatible code, FastAPI project foundation from slice 1, SQLite, pytest, stdlib `email.utils`, `html.parser`, and `urllib.parse`.

---

## Scope

This plan implements the testable Gmail discovery core only:

- Trusted source definitions for Seeking Alpha, Zacks, and Investing.com.
- Sender and link-domain source matching.
- Gmail unread/trusted-source query construction.
- Gmail message candidate filtering.
- Main/headline article link extraction from email HTML or text.
- Gmail success/failure label transition orchestration through an interface.
- SQLite tables for discovered Gmail messages and selected article links.

This plan intentionally does not implement live Gmail OAuth, real Google API client calls, browser capture, OpenAI analysis, or dashboard screens.

## File Structure

- `src/email_article_analyzer/db.py` - extend schema with `gmail_messages` and `article_links`.
- `src/email_article_analyzer/sources.py` - trusted source definitions and matching helpers.
- `src/email_article_analyzer/gmail.py` - provider protocols, discovery service, query builder, candidate and label logic.
- `src/email_article_analyzer/link_extraction.py` - headline-link extraction from email HTML/text.
- `src/email_article_analyzer/repositories.py` - repositories for Gmail messages and article links.
- `tests/test_sources.py` - source matching tests.
- `tests/test_gmail_query.py` - Gmail query tests.
- `tests/test_link_extraction.py` - headline-link extraction tests.
- `tests/test_gmail_discovery.py` - candidate filtering and label transition tests.
- `tests/test_gmail_repositories.py` - persistence tests.

## Task 1: Trusted Source Matching

**Files:**

- Create: `src/email_article_analyzer/sources.py`
- Test: `tests/test_sources.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_sources.py`:

```python
from email_article_analyzer.sources import (
    TRUSTED_SOURCES,
    match_source_for_sender,
    match_source_for_url,
)


def test_trusted_sources_include_initial_mvp_sources():
    keys = {source.source_key for source in TRUSTED_SOURCES}

    assert {"seeking_alpha", "zacks", "investing"} <= keys


def test_match_source_for_sender_handles_common_newsletter_senders():
    assert match_source_for_sender("alerts@seekingalpha.com").source_key == "seeking_alpha"
    assert match_source_for_sender("newsletter@zacks.com").source_key == "zacks"
    assert match_source_for_sender("updates@investing.com").source_key == "investing"


def test_match_source_for_url_uses_article_domains():
    assert match_source_for_url("https://seekingalpha.com/article/123-test").source_key == "seeking_alpha"
    assert match_source_for_url("https://www.zacks.com/stock/news/123-test").source_key == "zacks"
    assert match_source_for_url("https://www.investing.com/news/stock-market-news/test").source_key == "investing"


def test_unknown_sender_or_url_returns_none():
    assert match_source_for_sender("person@example.com") is None
    assert match_source_for_url("https://example.com/article") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='src'; C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe -m pytest tests/test_sources.py -v
```

Expected: FAIL because `email_article_analyzer.sources` does not exist.

- [ ] **Step 3: Implement source matching**

Create `src/email_article_analyzer/sources.py`:

```python
from dataclasses import dataclass
from email.utils import parseaddr
from urllib.parse import urlparse


@dataclass(frozen=True)
class TrustedSource:
    source_key: str
    display_name: str
    sender_domains: tuple[str, ...]
    article_domains: tuple[str, ...]
    login_url: str


TRUSTED_SOURCES: tuple[TrustedSource, ...] = (
    TrustedSource(
        source_key="seeking_alpha",
        display_name="Seeking Alpha",
        sender_domains=("seekingalpha.com",),
        article_domains=("seekingalpha.com", "www.seekingalpha.com"),
        login_url="https://seekingalpha.com/account/login",
    ),
    TrustedSource(
        source_key="zacks",
        display_name="Zacks",
        sender_domains=("zacks.com",),
        article_domains=("zacks.com", "www.zacks.com"),
        login_url="https://www.zacks.com/login",
    ),
    TrustedSource(
        source_key="investing",
        display_name="Investing.com",
        sender_domains=("investing.com",),
        article_domains=("investing.com", "www.investing.com"),
        login_url="https://www.investing.com/login",
    ),
)


def match_source_for_sender(sender: str) -> TrustedSource | None:
    _, address = parseaddr(sender)
    domain = address.lower().split("@")[-1] if "@" in address else sender.lower()
    for source in TRUSTED_SOURCES:
        if any(domain == sender_domain or domain.endswith(f".{sender_domain}") for sender_domain in source.sender_domains):
            return source
    return None


def match_source_for_url(url: str) -> TrustedSource | None:
    host = (urlparse(url).hostname or "").lower()
    for source in TRUSTED_SOURCES:
        if any(host == domain or host.endswith(f".{domain}") for domain in source.article_domains):
            return source
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
$env:PYTHONPATH='src'; C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe -m pytest tests/test_sources.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/email_article_analyzer/sources.py tests/test_sources.py
git commit -m "Add trusted source matching"
```

## Task 2: Headline Link Extraction

**Files:**

- Create: `src/email_article_analyzer/link_extraction.py`
- Test: `tests/test_link_extraction.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_link_extraction.py`:

```python
from email_article_analyzer.link_extraction import extract_headline_link
from email_article_analyzer.sources import TRUSTED_SOURCES


SEEKING_ALPHA = next(source for source in TRUSTED_SOURCES if source.source_key == "seeking_alpha")


def test_extract_headline_link_prefers_large_headline_anchor():
    html = '''
    <html>
      <body>
        <a href="https://seekingalpha.com/account">Account</a>
        <h1><a href="https://seekingalpha.com/article/123-main-story">Main Story</a></h1>
        <a href="https://seekingalpha.com/article/456-related">Related</a>
      </body>
    </html>
    '''

    result = extract_headline_link(html=html, text="", source=SEEKING_ALPHA)

    assert result.url == "https://seekingalpha.com/article/123-main-story"
    assert result.detection_method == "headline_anchor"


def test_extract_headline_link_falls_back_to_first_article_domain_link():
    html = '''
    <a href="https://example.com/not-source">Ad</a>
    <a href="https://seekingalpha.com/article/789-first-valid">First Valid</a>
    '''

    result = extract_headline_link(html=html, text="", source=SEEKING_ALPHA)

    assert result.url == "https://seekingalpha.com/article/789-first-valid"
    assert result.detection_method == "first_valid_link"


def test_extract_headline_link_can_read_plain_text_urls():
    text = "Read now: https://seekingalpha.com/article/999-text-story"

    result = extract_headline_link(html="", text=text, source=SEEKING_ALPHA)

    assert result.url == "https://seekingalpha.com/article/999-text-story"
    assert result.detection_method == "first_text_url"


def test_extract_headline_link_returns_none_when_no_source_link_exists():
    assert extract_headline_link(html="<a href='https://example.com'>x</a>", text="", source=SEEKING_ALPHA) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='src'; C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe -m pytest tests/test_link_extraction.py -v
```

Expected: FAIL because `email_article_analyzer.link_extraction` does not exist.

- [ ] **Step 3: Implement headline extraction**

Create `src/email_article_analyzer/link_extraction.py`:

```python
from dataclasses import dataclass
from html.parser import HTMLParser
import re

from email_article_analyzer.sources import TrustedSource, match_source_for_url


@dataclass(frozen=True)
class ExtractedLink:
    url: str
    detection_method: str
    detection_confidence: float


class _AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_heading = False
        self.anchors: list[tuple[str, bool]] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"h1", "h2"}:
            self.in_heading = True
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href:
                self.anchors.append((href, self.in_heading))

    def handle_endtag(self, tag):
        if tag.lower() in {"h1", "h2"}:
            self.in_heading = False


def extract_headline_link(html: str, text: str, source: TrustedSource) -> ExtractedLink | None:
    parser = _AnchorParser()
    parser.feed(html or "")

    source_links = [
        (href, in_heading)
        for href, in_heading in parser.anchors
        if _belongs_to_source(href, source)
    ]
    for href, in_heading in source_links:
        if in_heading:
            return ExtractedLink(href, "headline_anchor", 0.9)
    if source_links:
        return ExtractedLink(source_links[0][0], "first_valid_link", 0.65)

    for url in re.findall(r"https?://\\S+", text or ""):
        cleaned = url.rstrip(").,;]")
        if _belongs_to_source(cleaned, source):
            return ExtractedLink(cleaned, "first_text_url", 0.55)
    return None


def _belongs_to_source(url: str, source: TrustedSource) -> bool:
    matched = match_source_for_url(url)
    return matched is not None and matched.source_key == source.source_key
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
$env:PYTHONPATH='src'; C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe -m pytest tests/test_link_extraction.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/email_article_analyzer/link_extraction.py tests/test_link_extraction.py
git commit -m "Add headline link extraction"
```

## Task 3: Gmail Query and Discovery Service

**Files:**

- Create: `src/email_article_analyzer/gmail.py`
- Test: `tests/test_gmail_query.py`
- Test: `tests/test_gmail_discovery.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_gmail_query.py`:

```python
from email_article_analyzer.gmail import build_unread_trusted_query
from email_article_analyzer.sources import TRUSTED_SOURCES


def test_build_unread_trusted_query_targets_unread_and_excludes_analyzed():
    query = build_unread_trusted_query(TRUSTED_SOURCES)

    assert "is:unread" in query
    assert "-label:Analyzed" in query
    assert "from:seekingalpha.com" in query
    assert "from:zacks.com" in query
    assert "from:investing.com" in query
```

Create `tests/test_gmail_discovery.py`:

```python
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
            GmailMessage("1", "thread-1", "alerts@seekingalpha.com", "SA", [], "<h1><a href='https://seekingalpha.com/article/1'>A</a></h1>", ""),
            GmailMessage("2", "thread-2", "person@example.com", "Noise", [], "<a href='https://example.com'>x</a>", ""),
            GmailMessage("3", "thread-3", "newsletter@zacks.com", "Done", ["Analyzed"], "<a href='https://www.zacks.com/stock/news/1'>Z</a>", ""),
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH='src'; C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe -m pytest tests/test_gmail_query.py tests/test_gmail_discovery.py -v
```

Expected: FAIL because `email_article_analyzer.gmail` does not exist.

- [ ] **Step 3: Implement Gmail discovery service**

Create `src/email_article_analyzer/gmail.py`:

```python
from dataclasses import dataclass
from typing import Protocol

from email_article_analyzer.link_extraction import ExtractedLink, extract_headline_link
from email_article_analyzer.sources import TrustedSource, match_source_for_sender

ANALYZED_LABEL = "Analyzed"
FAILED_LABEL = "Analysis Failed"


@dataclass(frozen=True)
class GmailMessage:
    message_id: str
    thread_id: str
    sender: str
    subject: str
    labels: list[str]
    html_body: str
    text_body: str


@dataclass(frozen=True)
class GmailCandidate:
    message: GmailMessage
    source: TrustedSource
    headline_link: ExtractedLink


class GmailProvider(Protocol):
    def search_unread_messages(self, query: str) -> list[GmailMessage]:
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
        messages = self.provider.search_unread_messages(build_unread_trusted_query(self.sources))
        candidates: list[GmailCandidate] = []
        for message in messages:
            if ANALYZED_LABEL in message.labels:
                continue
            source = match_source_for_sender(message.sender)
            if source is None:
                continue
            headline_link = extract_headline_link(message.html_body, message.text_body, source)
            if headline_link is None:
                continue
            candidates.append(GmailCandidate(message=message, source=source, headline_link=headline_link))
        return candidates

    def mark_success(self, message_id: str) -> None:
        self.provider.mark_read(message_id)
        self.provider.add_label(message_id, ANALYZED_LABEL)
        self.provider.remove_label(message_id, FAILED_LABEL)

    def mark_failure(self, message_id: str) -> None:
        self.provider.add_label(message_id, FAILED_LABEL)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
$env:PYTHONPATH='src'; C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe -m pytest tests/test_gmail_query.py tests/test_gmail_discovery.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/email_article_analyzer/gmail.py tests/test_gmail_query.py tests/test_gmail_discovery.py
git commit -m "Add Gmail discovery service"
```

## Task 4: Gmail Discovery Persistence

**Files:**

- Modify: `src/email_article_analyzer/db.py`
- Modify: `src/email_article_analyzer/repositories.py`
- Test: `tests/test_gmail_repositories.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write failing persistence tests**

Create `tests/test_gmail_repositories.py`:

```python
from email_article_analyzer.db import initialize_database
from email_article_analyzer.repositories import GmailDiscoveryRepository


def test_gmail_repository_saves_message_and_article_link(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    repo = GmailDiscoveryRepository(db_path)

    gmail_row_id = repo.save_message(
        run_id=None,
        gmail_message_id="msg-1",
        thread_id="thread-1",
        sender="alerts@seekingalpha.com",
        subject="Story",
        labels=["UNREAD"],
        source_key="seeking_alpha",
        processing_status="discovered",
    )
    link_id = repo.save_article_link(
        gmail_message_row_id=gmail_row_id,
        source_key="seeking_alpha",
        raw_url="https://seekingalpha.com/article/1",
        normalized_url="https://seekingalpha.com/article/1",
        detection_method="headline_anchor",
        detection_confidence=0.9,
        heuristic_notes="h1 anchor",
    )

    message = repo.get_message(gmail_row_id)
    link = repo.get_article_link(link_id)

    assert message["gmail_message_id"] == "msg-1"
    assert message["labels_json"] == "[\"UNREAD\"]"
    assert link["detection_method"] == "headline_anchor"
```

Modify `tests/test_db.py` table assertion to include:

```python
"gmail_messages",
"article_links",
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH='src'; C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe -m pytest tests/test_db.py tests/test_gmail_repositories.py -v
```

Expected: FAIL because tables and repository are missing.

- [ ] **Step 3: Add schema and repository**

Extend `SCHEMA` in `src/email_article_analyzer/db.py` with:

```sql
CREATE TABLE IF NOT EXISTS gmail_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    gmail_message_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    received_at TEXT,
    labels_json TEXT NOT NULL,
    was_unread_at_discovery INTEGER NOT NULL DEFAULT 1,
    source_key TEXT NOT NULL,
    processing_status TEXT NOT NULL,
    failure_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS article_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_message_id INTEGER NOT NULL,
    source_key TEXT NOT NULL,
    raw_url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    detection_method TEXT NOT NULL,
    detection_confidence REAL NOT NULL,
    heuristic_notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (gmail_message_id) REFERENCES gmail_messages(id)
);
```

Append to `src/email_article_analyzer/repositories.py`:

```python

class GmailDiscoveryRepository:
    def __init__(self, database_path: str):
        self.database_path = database_path

    def save_message(
        self,
        run_id: int | None,
        gmail_message_id: str,
        thread_id: str,
        sender: str,
        subject: str,
        labels: list[str],
        source_key: str,
        processing_status: str,
        received_at: str | None = None,
        failure_reason: str | None = None,
    ) -> int:
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO gmail_messages (
                    run_id, gmail_message_id, thread_id, sender, subject, received_at,
                    labels_json, source_key, processing_status, failure_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    gmail_message_id,
                    thread_id,
                    sender,
                    subject,
                    received_at,
                    json.dumps(labels),
                    source_key,
                    processing_status,
                    failure_reason,
                ),
            )
            return int(cursor.lastrowid)

    def save_article_link(
        self,
        gmail_message_row_id: int,
        source_key: str,
        raw_url: str,
        normalized_url: str,
        detection_method: str,
        detection_confidence: float,
        heuristic_notes: str | None,
    ) -> int:
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO article_links (
                    gmail_message_id, source_key, raw_url, normalized_url,
                    detection_method, detection_confidence, heuristic_notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    gmail_message_row_id,
                    source_key,
                    raw_url,
                    normalized_url,
                    detection_method,
                    detection_confidence,
                    heuristic_notes,
                ),
            )
            return int(cursor.lastrowid)

    def get_message(self, row_id: int) -> dict[str, Any]:
        with connect(self.database_path) as conn:
            row = conn.execute("SELECT * FROM gmail_messages WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            raise KeyError(f"Gmail message not found: {row_id}")
        return dict(row)

    def get_article_link(self, row_id: int) -> dict[str, Any]:
        with connect(self.database_path) as conn:
            row = conn.execute("SELECT * FROM article_links WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            raise KeyError(f"Article link not found: {row_id}")
        return dict(row)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
$env:PYTHONPATH='src'; C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe -m pytest tests/test_db.py tests/test_gmail_repositories.py -v
```

Expected: PASS.

- [ ] **Step 5: Run all tests**

Run:

```powershell
$env:PYTHONPATH='src'; C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe -m pytest -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/email_article_analyzer/db.py src/email_article_analyzer/repositories.py tests/test_db.py tests/test_gmail_repositories.py
git commit -m "Add Gmail discovery persistence"
```

## Self-Review

Spec coverage:

- Trusted sender mapping: Task 1.
- Unread Gmail query and skip `Analyzed`: Task 3.
- Headline-link detection: Task 2.
- Gmail label transitions: Task 3.
- Durable Gmail message/link storage: Task 4.

Deferred by design:

- Live Gmail OAuth and API client.
- Dashboard run controls for Gmail discovery.
- Browser capture jobs.
- Source-specific real newsletter tuning.

Marker scan:

- No unresolved planning markers remain.

Type consistency:

- `TrustedSource`, `GmailMessage`, `GmailCandidate`, and repository field names match planned schema names.
