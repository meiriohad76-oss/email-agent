# Live Product Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current email article analyzer foundation into a locally runnable live product where the user can configure providers, upload a watchlist, start a run, and review discovered articles with content-fetch and OpenAI analysis results in the dashboard.

**Architecture:** Keep the app as a FastAPI + SQLite + static dashboard product. Extend existing repositories and API payloads instead of adding a separate frontend framework. Continue small TDD slices, committing each slice after full verification.

**Tech Stack:** Python 3.14, FastAPI, SQLite, httpx, Google Gmail API client, OpenAI Responses API, static HTML/CSS/JS dashboard, pytest.

---

## File Structure

- `src/email_article_analyzer/repositories.py`: enrich run detail article rows with latest content and analysis fields.
- `tests/test_runs_api.py`: prove `/api/runs/{run_id}` returns article content and analysis payloads.
- `src/email_article_analyzer/static/dashboard.js`: render content status, summary, stance, confidence, evidence, and tickers per article.
- `src/email_article_analyzer/static/dashboard.css`: style analysis review rows without changing the operational dashboard layout.
- `tests/test_dashboard.py`: assert dashboard assets include analysis rendering hooks.
- `scripts/smoke_live_product.py`: create a temporary app database, insert representative run/content/analysis data, and verify core HTTP endpoints with `TestClient`.
- `docs/first-run-setup.md`: add the smoke command and live-run command sequence.
- `README.md`: create concise product run instructions if no README exists.

---

### Task 1: Expose Analysis In Run Detail API

**Files:**
- Modify: `tests/test_runs_api.py`
- Modify: `src/email_article_analyzer/repositories.py`

- [ ] **Step 1: Write the failing API test**

Add content and analysis rows in `test_get_run_endpoint_returns_status_counts_and_events`, then expect each article to include:

```python
"content": {
    "fetch_status": "fetched",
    "title": "Story title",
    "text_char_count": len("Article body text."),
    "failure_reason": None,
},
"analysis": {
    "provider": "openai",
    "model": "gpt-summary",
    "summary": "Margins improved.",
    "stance": "buy_watch",
    "confidence": 0.82,
    "supporting_evidence": ["Raised guide", "Margin expansion"],
    "mentioned_tickers": ["NVDA"],
},
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:PYTHONPATH='src'; & 'C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe' -m pytest tests/test_runs_api.py::test_get_run_endpoint_returns_status_counts_and_events -v
```

Expected: fail because the response article lacks `content` and `analysis`.

- [ ] **Step 3: Implement repository enrichment**

Update `RunRepository.list_discovered_articles()` to `LEFT JOIN` the latest `article_contents` and latest `article_analyses`, parse JSON fields with `json.loads`, and return nested `content` and `analysis` dictionaries or `None` when absent.

- [ ] **Step 4: Verify GREEN**

Run the same test and then:

```powershell
$env:PYTHONPATH='src'; & 'C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe' -m pytest tests/test_runs_api.py tests/test_gmail_repositories.py -v
```

- [ ] **Step 5: Commit**

```powershell
git add src/email_article_analyzer/repositories.py tests/test_runs_api.py
git commit -m "Expose article analysis in run detail API"
```

---

### Task 2: Render Analysis In Dashboard

**Files:**
- Modify: `tests/test_dashboard.py`
- Modify: `src/email_article_analyzer/static/dashboard.js`
- Modify: `src/email_article_analyzer/static/dashboard.css`

- [ ] **Step 1: Write the failing dashboard asset test**

Add assertions that the JavaScript contains `article-analysis`, `supporting_evidence`, and `fetch_status`, and CSS contains `.article-analysis`.

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:PYTHONPATH='src'; & 'C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe' -m pytest tests/test_dashboard.py -v
```

Expected: fail because the dashboard does not render analysis fields yet.

- [ ] **Step 3: Implement dashboard rendering**

Update `renderArticleRows(articles)` to add:

```javascript
const contentStatus = document.createElement("div");
contentStatus.className = `article-fetch-status ${article.content?.fetch_status || "missing"}`;
contentStatus.textContent = article.content
  ? `Content: ${article.content.fetch_status}${article.content.title ? ` - ${article.content.title}` : ""}`
  : "Content: not fetched";

const analysis = document.createElement("div");
analysis.className = "article-analysis";
```

Render summary, stance/confidence, tickers, evidence list, and failure reason when present.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
$env:PYTHONPATH='src'; & 'C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe' -m pytest tests/test_dashboard.py tests/test_runs_api.py -v
```

- [ ] **Step 5: Commit**

```powershell
git add src/email_article_analyzer/static/dashboard.js src/email_article_analyzer/static/dashboard.css tests/test_dashboard.py
git commit -m "Render article analysis in dashboard"
```

---

### Task 3: Add Local Live Product Smoke Check

**Files:**
- Create: `scripts/smoke_live_product.py`
- Modify: `docs/first-run-setup.md`
- Create or modify: `README.md`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing docs/CLI test**

Extend `tests/test_cli.py` to assert `docs/first-run-setup.md` mentions:

```text
python scripts/smoke_live_product.py
python -m uvicorn email_article_analyzer.main:app --host 127.0.0.1 --port 8000
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:PYTHONPATH='src'; & 'C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe' -m pytest tests/test_cli.py -v
```

- [ ] **Step 3: Implement smoke script and docs**

Create `scripts/smoke_live_product.py` that initializes a temporary DB, creates the app, checks `/api/health`, `/api/status/providers`, `/`, and `/api/runs`, and prints `Live product smoke check passed`.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
$env:PYTHONPATH='src'; & 'C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe' -m pytest tests/test_cli.py -v
$env:PYTHONPATH='src'; & 'C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe' scripts/smoke_live_product.py
```

- [ ] **Step 5: Commit**

```powershell
git add scripts/smoke_live_product.py docs/first-run-setup.md README.md tests/test_cli.py
git commit -m "Add live product smoke check"
```

---

### Task 4: Final Live Verification

**Files:**
- Modify only files required by failures discovered in verification.

- [ ] **Step 1: Run full automated verification**

```powershell
$env:PYTHONPATH='src'; & 'C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe' -m pytest -v
$env:PYTHONPATH='src'; & 'C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe' -m compileall -q src tests scripts
$env:PYTHONPATH='src'; & 'C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe' scripts/smoke_live_product.py
```

- [ ] **Step 2: Start the local app for manual/live trial**

```powershell
$env:PYTHONPATH='src'; & 'C:\Users\meiri\AppData\Local\Programs\Python\Python314\python.exe' -m uvicorn email_article_analyzer.main:app --host 127.0.0.1 --port 8000
```

Expected: dashboard is available at `http://127.0.0.1:8000/`.

- [ ] **Step 3: Final commit and push**

```powershell
git status --short
git push -u origin codex/mvp-foundation-watchlist
```

---

## Self-Review

- Spec coverage: The plan covers the immediate live usability gap: visible analysis review, setup/run documentation, and a smoke check. Full Gmail/OpenAI live execution still depends on user-provided credentials and tokens.
- Placeholder scan: No `TBD`, `TODO`, or unspecified implementation steps remain.
- Type consistency: The API uses existing `article_contents` and `article_analyses` names; dashboard reads nested `content` and `analysis` objects from `/api/runs/{run_id}`.
