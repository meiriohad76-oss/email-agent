# MVP Foundation and Watchlist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working backend slice for the stock email automation MVP: FastAPI foundation, configuration, SQLite persistence, run events, and watchlist CSV/Excel upload with Polygon-backed validation.

**Architecture:** Use a small Python FastAPI application with focused service modules and repository classes. Keep external systems behind interfaces so Gmail, OpenAI, Polygon, and the Windows helper can be added incrementally without rewriting core models or tests.

**Tech Stack:** Python 3.14-compatible code, FastAPI, Uvicorn, SQLite, Pydantic, pytest, httpx/TestClient, openpyxl for Excel parsing, python-dotenv for local configuration.

---

## Scope

This plan implements the first buildable subsystem from the approved design review:

- Project scaffold.
- Configuration loading.
- SQLite schema and database helper.
- Health endpoint.
- Run and event persistence.
- Watchlist upload parsing for CSV/XLSX.
- Flexible column mapping.
- Polygon validation adapter interface.
- Active watchlist replacement after validation.
- Tests for each behavior.

This plan intentionally does not implement Gmail, browser helper, OpenAI analysis, Polygon last-close enrichment, downstream signal API, or dashboard screens beyond API foundations.

## File Structure

- `pyproject.toml` - project metadata, dependencies, and pytest configuration.
- `.env.example` - documented local environment variables.
- `.gitignore` - Python caches, virtualenvs, local DB, `.env`, and worktrees.
- `src/email_article_analyzer/__init__.py` - package marker.
- `src/email_article_analyzer/config.py` - environment configuration model.
- `src/email_article_analyzer/db.py` - SQLite connection and schema initialization.
- `src/email_article_analyzer/main.py` - FastAPI app factory and route registration.
- `src/email_article_analyzer/models.py` - shared enums and typed domain models.
- `src/email_article_analyzer/repositories.py` - database repositories for runs, events, watchlist uploads, and watchlist items.
- `src/email_article_analyzer/watchlist.py` - file parsing, column mapping, ticker normalization, validation orchestration.
- `src/email_article_analyzer/providers/polygon.py` - Polygon client interface plus HTTP implementation.
- `src/email_article_analyzer/api/health.py` - health routes.
- `src/email_article_analyzer/api/watchlist.py` - watchlist upload, validation, and replacement routes.
- `tests/conftest.py` - temporary app/database fixtures.
- `tests/test_config.py` - configuration tests.
- `tests/test_db.py` - schema and database tests.
- `tests/test_health_api.py` - health endpoint tests.
- `tests/test_watchlist_parser.py` - CSV/XLSX parsing tests.
- `tests/test_watchlist_service.py` - validation/replacement tests.
- `tests/test_watchlist_api.py` - API contract tests.

## Task 1: Project Scaffold and Configuration

**Files:**

- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `src/email_article_analyzer/__init__.py`
- Create: `src/email_article_analyzer/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing configuration test**

Create `tests/test_config.py`:

```python
from email_article_analyzer.config import AppConfig


def test_config_loads_defaults_for_local_development(monkeypatch):
    monkeypatch.delenv("APP_DATABASE_PATH", raising=False)
    monkeypatch.delenv("APP_DASHBOARD_PASSWORD", raising=False)
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)

    config = AppConfig.from_env()

    assert config.database_path.endswith("data/app.db")
    assert config.dashboard_password == "change-me"
    assert config.polygon_api_key is None


def test_config_reads_environment_overrides(monkeypatch):
    monkeypatch.setenv("APP_DATABASE_PATH", "custom/test.db")
    monkeypatch.setenv("APP_DASHBOARD_PASSWORD", "secret")
    monkeypatch.setenv("POLYGON_API_KEY", "polygon-key")

    config = AppConfig.from_env()

    assert config.database_path == "custom/test.db"
    assert config.dashboard_password == "secret"
    assert config.polygon_api_key == "polygon-key"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_config.py -v
```

Expected: FAIL because `email_article_analyzer.config` does not exist.

- [ ] **Step 3: Add project files and minimal config implementation**

Create `pyproject.toml`:

```toml
[project]
name = "email-article-analyzer"
version = "0.1.0"
description = "Local stock email article automation backend"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.111",
  "uvicorn[standard]>=0.30",
  "pydantic>=2.7",
  "python-dotenv>=1.0",
  "python-multipart>=0.0.9",
  "openpyxl>=3.1",
  "httpx>=0.27",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.2",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

Create `.env.example`:

```env
APP_DATABASE_PATH=data/app.db
APP_DASHBOARD_PASSWORD=change-me
POLYGON_API_KEY=
```

Create `.gitignore`:

```gitignore
.env
.venv/
__pycache__/
.pytest_cache/
data/
.worktrees/
*.pyc
```

Create `src/email_article_analyzer/__init__.py`:

```python
__all__ = ["__version__"]

__version__ = "0.1.0"
```

Create `src/email_article_analyzer/config.py`:

```python
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class AppConfig:
    database_path: str
    dashboard_password: str
    polygon_api_key: str | None

    @classmethod
    def from_env(cls) -> "AppConfig":
        polygon_key = os.getenv("POLYGON_API_KEY") or None
        return cls(
            database_path=os.getenv("APP_DATABASE_PATH", "data/app.db"),
            dashboard_password=os.getenv("APP_DASHBOARD_PASSWORD", "change-me"),
            polygon_api_key=polygon_key,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_config.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add pyproject.toml .env.example .gitignore src/email_article_analyzer/__init__.py src/email_article_analyzer/config.py tests/test_config.py
git commit -m "Add backend project configuration"
```

## Task 2: SQLite Schema and Database Helper

**Files:**

- Create: `src/email_article_analyzer/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing database schema test**

Create `tests/test_db.py`:

```python
import sqlite3

from email_article_analyzer.db import initialize_database


def table_names(db_path):
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {row[0] for row in rows}


def test_initialize_database_creates_foundation_tables(tmp_path):
    db_path = tmp_path / "app.db"

    initialize_database(str(db_path))

    assert {
        "runs",
        "run_events",
        "watchlist_uploads",
        "watchlist_items",
        "trusted_sources",
    }.issubset(table_names(db_path))
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_db.py -v
```

Expected: FAIL because `email_article_analyzer.db` does not exist.

- [ ] **Step 3: Implement database initialization**

Create `src/email_article_analyzer/db.py`:

```python
from pathlib import Path
import sqlite3


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,
    extraction_model TEXT,
    summary_model TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    error_summary TEXT
);

CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    event_type TEXT NOT NULL,
    stage TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    severity TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS watchlist_uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_filename TEXT NOT NULL,
    columns_json TEXT NOT NULL,
    sample_rows_json TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS watchlist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    normalized_ticker TEXT NOT NULL UNIQUE,
    company_name TEXT,
    sector TEXT,
    priority TEXT,
    notes TEXT,
    source_upload_id INTEGER,
    polygon_validation_status TEXT NOT NULL,
    polygon_reference TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_upload_id) REFERENCES watchlist_uploads(id)
);

CREATE TABLE IF NOT EXISTS trusted_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    sender_patterns_json TEXT NOT NULL,
    article_domains_json TEXT NOT NULL,
    login_url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);
"""


def connect(database_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database(database_path: str) -> None:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(str(path)) as conn:
        conn.executescript(SCHEMA)
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_db.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/email_article_analyzer/db.py tests/test_db.py
git commit -m "Add SQLite foundation schema"
```

## Task 3: FastAPI App and Health Endpoint

**Files:**

- Create: `src/email_article_analyzer/main.py`
- Create: `src/email_article_analyzer/api/__init__.py`
- Create: `src/email_article_analyzer/api/health.py`
- Test: `tests/test_health_api.py`

- [ ] **Step 1: Write the failing API test**

Create `tests/test_health_api.py`:

```python
from fastapi.testclient import TestClient

from email_article_analyzer.main import create_app


def test_health_endpoint_reports_ok(tmp_path):
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_health_api.py -v
```

Expected: FAIL because `email_article_analyzer.main` does not exist.

- [ ] **Step 3: Implement app factory and health route**

Create `src/email_article_analyzer/api/__init__.py`:

```python
"""HTTP API route modules."""
```

Create `src/email_article_analyzer/api/health.py`:

```python
from fastapi import APIRouter

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

Create `src/email_article_analyzer/main.py`:

```python
from fastapi import FastAPI

from email_article_analyzer.api.health import router as health_router
from email_article_analyzer.config import AppConfig
from email_article_analyzer.db import initialize_database


def create_app(database_path: str | None = None) -> FastAPI:
    config = AppConfig.from_env()
    resolved_database_path = database_path or config.database_path
    initialize_database(resolved_database_path)

    app = FastAPI(title="Email Article Analyzer")
    app.state.database_path = resolved_database_path
    app.include_router(health_router)
    return app


app = create_app()
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_health_api.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/email_article_analyzer/main.py src/email_article_analyzer/api/__init__.py src/email_article_analyzer/api/health.py tests/test_health_api.py
git commit -m "Add FastAPI health endpoint"
```

## Task 4: Run Event Repository

**Files:**

- Create: `src/email_article_analyzer/repositories.py`
- Test: `tests/test_run_events.py`

- [ ] **Step 1: Write the failing repository test**

Create `tests/test_run_events.py`:

```python
from email_article_analyzer.db import initialize_database
from email_article_analyzer.repositories import RunRepository


def test_run_repository_creates_run_and_event(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    repo = RunRepository(db_path)

    run_id = repo.create_run(extraction_model="gpt-test-extract", summary_model="gpt-test-summary")
    repo.add_event(
        run_id=run_id,
        event_type="run_started",
        stage="startup",
        message="Run started",
        details={"source": "test"},
    )

    run = repo.get_run(run_id)
    events = repo.list_events(run_id)

    assert run["status"] == "running"
    assert run["extraction_model"] == "gpt-test-extract"
    assert events[0]["event_type"] == "run_started"
    assert events[0]["details_json"] == '{"source": "test"}'
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_run_events.py -v
```

Expected: FAIL because `RunRepository` does not exist.

- [ ] **Step 3: Implement run repository**

Create `src/email_article_analyzer/repositories.py`:

```python
import json
from typing import Any

from email_article_analyzer.db import connect


class RunRepository:
    def __init__(self, database_path: str):
        self.database_path = database_path

    def create_run(self, extraction_model: str | None, summary_model: str | None) -> int:
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO runs (status, extraction_model, summary_model)
                VALUES (?, ?, ?)
                """,
                ("running", extraction_model, summary_model),
            )
            return int(cursor.lastrowid)

    def add_event(
        self,
        run_id: int | None,
        event_type: str,
        stage: str,
        message: str,
        details: dict[str, Any] | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        severity: str = "info",
    ) -> int:
        details_json = json.dumps(details or {}, sort_keys=True)
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO run_events (
                    run_id, event_type, stage, entity_type, entity_id,
                    severity, message, details_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    event_type,
                    stage,
                    entity_type,
                    entity_id,
                    severity,
                    message,
                    details_json,
                ),
            )
            return int(cursor.lastrowid)

    def get_run(self, run_id: int) -> dict[str, Any]:
        with connect(self.database_path) as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"Run not found: {run_id}")
        return dict(row)

    def list_events(self, run_id: int) -> list[dict[str, Any]]:
        with connect(self.database_path) as conn:
            rows = conn.execute(
                "SELECT * FROM run_events WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_run_events.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/email_article_analyzer/repositories.py tests/test_run_events.py
git commit -m "Add run event repository"
```

## Task 5: Watchlist File Parser

**Files:**

- Create: `src/email_article_analyzer/watchlist.py`
- Test: `tests/test_watchlist_parser.py`

- [ ] **Step 1: Write the failing parser tests**

Create `tests/test_watchlist_parser.py`:

```python
from io import BytesIO

from openpyxl import Workbook

from email_article_analyzer.watchlist import parse_watchlist_file, normalize_ticker


def test_normalize_ticker_trims_uppercases_and_removes_exchange_suffix():
    assert normalize_ticker(" aapl ") == "AAPL"
    assert normalize_ticker("nasdaq:msft") == "MSFT"
    assert normalize_ticker("$tsla") == "TSLA"


def test_parse_watchlist_csv_returns_columns_and_rows():
    content = b"Symbol,Name\\nAAPL,Apple Inc.\\nMSFT,Microsoft\\n"

    parsed = parse_watchlist_file("watchlist.csv", content)

    assert parsed.columns == ["Symbol", "Name"]
    assert parsed.rows == [
        {"Symbol": "AAPL", "Name": "Apple Inc."},
        {"Symbol": "MSFT", "Name": "Microsoft"},
    ]


def test_parse_watchlist_xlsx_returns_columns_and_rows():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Ticker", "Company"])
    sheet.append(["NVDA", "NVIDIA"])
    buffer = BytesIO()
    workbook.save(buffer)

    parsed = parse_watchlist_file("watchlist.xlsx", buffer.getvalue())

    assert parsed.columns == ["Ticker", "Company"]
    assert parsed.rows == [{"Ticker": "NVDA", "Company": "NVIDIA"}]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_watchlist_parser.py -v
```

Expected: FAIL because `watchlist.py` does not exist.

- [ ] **Step 3: Implement parser**

Create `src/email_article_analyzer/watchlist.py`:

```python
from dataclasses import dataclass
import csv
from io import BytesIO, StringIO
import re

from openpyxl import load_workbook


@dataclass(frozen=True)
class ParsedWatchlist:
    columns: list[str]
    rows: list[dict[str, str]]


def normalize_ticker(value: str) -> str:
    ticker = value.strip().upper()
    ticker = ticker.removeprefix("$")
    if ":" in ticker:
        ticker = ticker.split(":", 1)[1]
    return re.sub(r"[^A-Z0-9.\-]", "", ticker)


def parse_watchlist_file(filename: str, content: bytes) -> ParsedWatchlist:
    lower_name = filename.lower()
    if lower_name.endswith(".csv"):
        return _parse_csv(content)
    if lower_name.endswith(".xlsx"):
        return _parse_xlsx(content)
    raise ValueError("Unsupported watchlist file type. Use CSV or XLSX.")


def _parse_csv(content: bytes) -> ParsedWatchlist:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(StringIO(text))
    columns = list(reader.fieldnames or [])
    rows = [
        {column: (row.get(column) or "").strip() for column in columns}
        for row in reader
    ]
    return ParsedWatchlist(columns=columns, rows=rows)


def _parse_xlsx(content: bytes) -> ParsedWatchlist:
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    sheet = workbook.active
    values = list(sheet.iter_rows(values_only=True))
    if not values:
        return ParsedWatchlist(columns=[], rows=[])
    columns = [str(cell or "").strip() for cell in values[0]]
    rows: list[dict[str, str]] = []
    for row in values[1:]:
        mapped = {
            columns[index]: str(row[index] or "").strip()
            for index in range(len(columns))
        }
        if any(mapped.values()):
            rows.append(mapped)
    return ParsedWatchlist(columns=columns, rows=rows)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_watchlist_parser.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/email_article_analyzer/watchlist.py tests/test_watchlist_parser.py
git commit -m "Add watchlist file parser"
```

## Task 6: Watchlist Validation and Replacement Service

**Files:**

- Modify: `src/email_article_analyzer/repositories.py`
- Modify: `src/email_article_analyzer/watchlist.py`
- Create: `src/email_article_analyzer/providers/__init__.py`
- Create: `src/email_article_analyzer/providers/polygon.py`
- Test: `tests/test_watchlist_service.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/test_watchlist_service.py`:

```python
from dataclasses import dataclass

from email_article_analyzer.db import initialize_database
from email_article_analyzer.repositories import WatchlistRepository
from email_article_analyzer.watchlist import ParsedWatchlist, WatchlistService


@dataclass
class FakePolygonValidator:
    valid_tickers: set[str]

    def validate_ticker(self, ticker: str):
        if ticker in self.valid_tickers:
            return {"ticker": ticker, "name": f"{ticker} Corp"}
        return None


def test_validate_mapping_splits_valid_and_invalid_rows(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    service = WatchlistService(
        repository=WatchlistRepository(db_path),
        polygon_validator=FakePolygonValidator({"AAPL"}),
    )
    parsed = ParsedWatchlist(
        columns=["Symbol", "Name"],
        rows=[
            {"Symbol": "AAPL", "Name": "Apple"},
            {"Symbol": "BAD!", "Name": "Broken"},
        ],
    )

    result = service.validate(parsed, ticker_column="Symbol", optional_columns={"company_name": "Name"})

    assert [row.normalized_ticker for row in result.valid_rows] == ["AAPL"]
    assert result.invalid_rows[0].raw_ticker == "BAD!"


def test_replace_active_watchlist_deletes_old_rows_and_saves_valid_rows(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    repository = WatchlistRepository(db_path)
    service = WatchlistService(
        repository=repository,
        polygon_validator=FakePolygonValidator({"AAPL", "MSFT"}),
    )
    first = ParsedWatchlist(columns=["Ticker"], rows=[{"Ticker": "AAPL"}])
    second = ParsedWatchlist(columns=["Ticker"], rows=[{"Ticker": "MSFT"}])

    service.replace_active_watchlist("first.csv", first, ticker_column="Ticker", optional_columns={})
    service.replace_active_watchlist("second.csv", second, ticker_column="Ticker", optional_columns={})

    items = repository.list_active_items()
    assert [item["normalized_ticker"] for item in items] == ["MSFT"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_watchlist_service.py -v
```

Expected: FAIL because `WatchlistRepository` and `WatchlistService` do not exist.

- [ ] **Step 3: Implement provider interface, repository, and service**

Append to `src/email_article_analyzer/repositories.py`:

```python

class WatchlistRepository:
    def __init__(self, database_path: str):
        self.database_path = database_path

    def create_upload(self, original_filename: str, columns: list[str], sample_rows: list[dict[str, str]], row_count: int) -> int:
        details_columns = json.dumps(columns)
        details_sample = json.dumps(sample_rows)
        with connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO watchlist_uploads (
                    original_filename, columns_json, sample_rows_json, row_count
                )
                VALUES (?, ?, ?, ?)
                """,
                (original_filename, details_columns, details_sample, row_count),
            )
            return int(cursor.lastrowid)

    def replace_items(self, upload_id: int, items: list[dict[str, str | None]]) -> None:
        with connect(self.database_path) as conn:
            conn.execute("DELETE FROM watchlist_items")
            conn.executemany(
                """
                INSERT INTO watchlist_items (
                    ticker, normalized_ticker, company_name, sector, priority, notes,
                    source_upload_id, polygon_validation_status, polygon_reference
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item["ticker"],
                        item["normalized_ticker"],
                        item.get("company_name"),
                        item.get("sector"),
                        item.get("priority"),
                        item.get("notes"),
                        upload_id,
                        "valid",
                        item.get("polygon_reference"),
                    )
                    for item in items
                ],
            )

    def list_active_items(self) -> list[dict[str, Any]]:
        with connect(self.database_path) as conn:
            rows = conn.execute(
                "SELECT * FROM watchlist_items ORDER BY normalized_ticker"
            ).fetchall()
        return [dict(row) for row in rows]
```

Create `src/email_article_analyzer/providers/__init__.py`:

```python
"""External provider adapters."""
```

Create `src/email_article_analyzer/providers/polygon.py`:

```python
from typing import Protocol

import httpx


class PolygonTickerValidator(Protocol):
    def validate_ticker(self, ticker: str) -> dict | None:
        ...


class PolygonHttpClient:
    def __init__(self, api_key: str, base_url: str = "https://api.polygon.io"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def validate_ticker(self, ticker: str) -> dict | None:
        response = httpx.get(
            f"{self.base_url}/v3/reference/tickers/{ticker}",
            params={"apiKey": self.api_key},
            timeout=10,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        result = payload.get("results")
        if not result:
            return None
        return result
```

Append to `src/email_article_analyzer/watchlist.py`:

```python

@dataclass(frozen=True)
class ValidWatchlistRow:
    raw_ticker: str
    normalized_ticker: str
    values: dict[str, str]
    polygon_reference: dict


@dataclass(frozen=True)
class InvalidWatchlistRow:
    raw_ticker: str
    values: dict[str, str]
    reason: str


@dataclass(frozen=True)
class WatchlistValidationResult:
    valid_rows: list[ValidWatchlistRow]
    invalid_rows: list[InvalidWatchlistRow]


class WatchlistService:
    def __init__(self, repository, polygon_validator):
        self.repository = repository
        self.polygon_validator = polygon_validator

    def validate(
        self,
        parsed: ParsedWatchlist,
        ticker_column: str,
        optional_columns: dict[str, str],
    ) -> WatchlistValidationResult:
        valid_rows: list[ValidWatchlistRow] = []
        invalid_rows: list[InvalidWatchlistRow] = []

        for row in parsed.rows:
            raw_ticker = row.get(ticker_column, "")
            normalized = normalize_ticker(raw_ticker)
            if not normalized:
                invalid_rows.append(InvalidWatchlistRow(raw_ticker, row, "Missing ticker"))
                continue
            polygon_reference = self.polygon_validator.validate_ticker(normalized)
            if polygon_reference is None:
                invalid_rows.append(InvalidWatchlistRow(raw_ticker, row, "Polygon did not recognize ticker"))
                continue
            valid_rows.append(
                ValidWatchlistRow(
                    raw_ticker=raw_ticker,
                    normalized_ticker=normalized,
                    values=row,
                    polygon_reference=polygon_reference,
                )
            )
        return WatchlistValidationResult(valid_rows=valid_rows, invalid_rows=invalid_rows)

    def replace_active_watchlist(
        self,
        original_filename: str,
        parsed: ParsedWatchlist,
        ticker_column: str,
        optional_columns: dict[str, str],
    ) -> WatchlistValidationResult:
        result = self.validate(parsed, ticker_column, optional_columns)
        upload_id = self.repository.create_upload(
            original_filename=original_filename,
            columns=parsed.columns,
            sample_rows=parsed.rows[:5],
            row_count=len(parsed.rows),
        )
        items = []
        for row in result.valid_rows:
            values = row.values
            items.append(
                {
                    "ticker": row.raw_ticker,
                    "normalized_ticker": row.normalized_ticker,
                    "company_name": values.get(optional_columns.get("company_name", ""), None),
                    "sector": values.get(optional_columns.get("sector", ""), None),
                    "priority": values.get(optional_columns.get("priority", ""), None),
                    "notes": values.get(optional_columns.get("notes", ""), None),
                    "polygon_reference": str(row.polygon_reference),
                }
            )
        self.repository.replace_items(upload_id, items)
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_watchlist_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/email_article_analyzer/repositories.py src/email_article_analyzer/watchlist.py src/email_article_analyzer/providers/__init__.py src/email_article_analyzer/providers/polygon.py tests/test_watchlist_service.py
git commit -m "Add watchlist validation service"
```

## Task 7: Watchlist API

**Files:**

- Modify: `src/email_article_analyzer/main.py`
- Create: `src/email_article_analyzer/api/watchlist.py`
- Test: `tests/test_watchlist_api.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_watchlist_api.py`:

```python
from fastapi.testclient import TestClient

from email_article_analyzer.main import create_app


def test_upload_watchlist_returns_columns_and_sample_rows(tmp_path):
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    response = client.post(
        "/api/watchlist/upload",
        files={"file": ("watchlist.csv", b"Ticker,Name\\nAAPL,Apple\\n", "text/csv")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["columns"] == ["Ticker", "Name"]
    assert payload["sample_rows"] == [{"Ticker": "AAPL", "Name": "Apple"}]
    assert payload["row_count"] == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_watchlist_api.py -v
```

Expected: FAIL because `/api/watchlist/upload` does not exist.

- [ ] **Step 3: Implement upload API**

Create `src/email_article_analyzer/api/watchlist.py`:

```python
from fastapi import APIRouter, File, UploadFile

from email_article_analyzer.watchlist import parse_watchlist_file

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.post("/upload")
async def upload_watchlist(file: UploadFile = File(...)) -> dict:
    content = await file.read()
    parsed = parse_watchlist_file(file.filename or "watchlist.csv", content)
    return {
        "columns": parsed.columns,
        "sample_rows": parsed.rows[:5],
        "row_count": len(parsed.rows),
    }
```

Modify `src/email_article_analyzer/main.py`:

```python
from fastapi import FastAPI

from email_article_analyzer.api.health import router as health_router
from email_article_analyzer.api.watchlist import router as watchlist_router
from email_article_analyzer.config import AppConfig
from email_article_analyzer.db import initialize_database


def create_app(database_path: str | None = None) -> FastAPI:
    config = AppConfig.from_env()
    resolved_database_path = database_path or config.database_path
    initialize_database(resolved_database_path)

    app = FastAPI(title="Email Article Analyzer")
    app.state.database_path = resolved_database_path
    app.include_router(health_router)
    app.include_router(watchlist_router)
    return app


app = create_app()
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_watchlist_api.py -v
```

Expected: PASS.

- [ ] **Step 5: Run all tests**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/email_article_analyzer/main.py src/email_article_analyzer/api/watchlist.py tests/test_watchlist_api.py
git commit -m "Add watchlist upload API"
```

## Self-Review

Spec coverage:

- Project foundation: covered by Tasks 1-3.
- SQLite foundation: covered by Task 2.
- Run events: covered by Task 4.
- Watchlist CSV/Excel upload: covered by Tasks 5 and 7.
- Flexible ticker column mapping: service accepts `ticker_column` and optional mapping in Task 6.
- Polygon validation before replacement: covered by Task 6.
- Active watchlist replacement: covered by Task 6.
- Dashboard/API foundations: covered by Task 7.

Deferred by design:

- Gmail discovery.
- Browser helper.
- OpenAI extraction.
- Polygon last-close enrichment.
- Signal lifecycle.
- Downstream API.
- Dashboard frontend.

Marker scan:

- No unresolved planning markers remain.
- Each task has test, expected failure, implementation, passing command, and commit command.

Type consistency:

- `ParsedWatchlist`, `WatchlistService`, `WatchlistRepository`, and `PolygonTickerValidator` names are used consistently.
- Database table names match the schema in Task 2.
