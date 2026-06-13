# Gmail API Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real Gmail API provider adapter that implements the existing `GmailProvider` protocol while keeping OAuth and live Gmail calls out of unit tests.

**Architecture:** Keep all Google API-specific code in `providers/gmail_api.py`. Use lazy imports for Google client libraries so core tests and non-Gmail development do not fail when credentials are absent. Parse Gmail API message payloads into the existing `GmailMessage` domain model.

**Tech Stack:** Python 3.14-compatible code, Google Gmail API client libraries, pytest with fake Gmail service objects.

---

## Scope

This plan implements:

- Gmail credential/token config fields.
- Gmail API dependencies in `pyproject.toml`.
- A Gmail API provider adapter.
- Gmail API message parsing into `GmailMessage`.
- Gmail search/read flow for unread messages.
- Label create/cache behavior by label name.
- Label add/remove and mark-read operations.

This plan does not perform live OAuth in tests, create dashboard screens, or call the real Gmail API during verification.

## Task 1: Gmail Configuration and Dependencies

**Files:**

- Modify: `pyproject.toml`
- Modify: `.env.example`
- Modify: `src/email_article_analyzer/config.py`
- Modify: `tests/test_config.py`

Steps:

1. Add failing tests for `gmail_credentials_path` and `gmail_token_path`.
2. Run config tests and confirm failure.
3. Add fields to `AppConfig`, environment loading, `.env.example`, and Gmail API dependencies.
4. Run config tests and confirm pass.
5. Commit with `Add Gmail API configuration`.

## Task 2: Gmail Message Payload Parsing

**Files:**

- Create: `src/email_article_analyzer/providers/gmail_api.py`
- Create: `tests/test_gmail_api_provider.py`

Steps:

1. Add failing tests for parsing Gmail API payload headers, labels, plain text body, and HTML body into `GmailMessage`.
2. Run tests and confirm failure.
3. Implement `parse_gmail_message`.
4. Run tests and confirm pass.
5. Commit with `Add Gmail API message parsing`.

## Task 3: Gmail Provider Search and Read

**Files:**

- Modify: `src/email_article_analyzer/providers/gmail_api.py`
- Modify: `tests/test_gmail_api_provider.py`

Steps:

1. Add failing tests using a fake Gmail service for `search_unread_messages`.
2. Run tests and confirm failure.
3. Implement `GmailApiProvider.search_unread_messages`.
4. Run tests and confirm pass.
5. Commit with `Add Gmail API search provider`.

## Task 4: Gmail Provider Labels

**Files:**

- Modify: `src/email_article_analyzer/providers/gmail_api.py`
- Modify: `tests/test_gmail_api_provider.py`

Steps:

1. Add failing tests for ensuring labels by name, adding labels, removing labels, and marking read.
2. Run tests and confirm failure.
3. Implement label cache, creation, and modify calls.
4. Run tests and confirm pass.
5. Run all tests and compile check.
6. Commit with `Add Gmail API label operations`.

## Self-Review

Spec coverage:

- Live Gmail client implementation boundary: covered.
- OAuth/config paths: covered.
- Search unread messages: covered.
- Read message body/metadata: covered.
- Apply/remove labels and mark read: covered.

Deferred:

- Dashboard configuration UI.
- Actual OAuth browser flow testing.
- End-to-end live Gmail smoke test.
