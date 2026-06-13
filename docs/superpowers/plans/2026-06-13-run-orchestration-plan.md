# Run Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a run orchestration service and API endpoints that start a Gmail discovery run, persist discovered candidates, record run events, calculate needed source logins, and return run status.

**Architecture:** Keep orchestration in a service module that accepts a discovery service dependency. API tests inject fake discovery services so live Gmail credentials are not required.

**Tech Stack:** Python 3.14-compatible code, FastAPI, SQLite repositories, pytest.

---

## Scope

This plan implements:

- Run repository completion/count support.
- Discovery orchestration service.
- Candidate persistence into `gmail_messages` and `article_links`.
- Run event creation for start, discovery, candidate, and completion.
- `POST /api/runs`.
- `GET /api/runs/{run_id}`.
- API dependency injection for tests and future real Gmail provider wiring.

Deferred:

- Live Gmail service construction from OAuth credentials.
- Background async job queue.
- Dashboard UI.
- Source login confirmation endpoints.

## Tasks

1. Add repository support for completing runs and counting persisted Gmail messages/article links.
2. Add `RunOrchestrator` with tests using fake Gmail discovery candidates.
3. Add run API endpoints with tests using dependency injection.
4. Run full verification and push.

## Acceptance Criteria

- Starting a run creates a `runs` row.
- Discovery candidates are persisted.
- One selected `article_links` row is saved per candidate.
- Run events record `run_started`, `gmail_search_started`, `headline_link_detected`, and `run_completed`.
- Run status reports counts and needed source logins.
- Tests do not require live Gmail credentials.
