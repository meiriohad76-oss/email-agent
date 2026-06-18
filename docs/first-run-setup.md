# First-Run Setup

Use this checklist before starting the local Email Article Analyzer dashboard.

## 1. Configure Environment Variables

Create a local `.env` file or set these variables in your shell:

```text
APP_DATABASE_PATH=data/app.db
APP_DASHBOARD_PASSWORD=change-me
OPENAI_API_KEY=your-openai-key
POLYGON_API_KEY=your-polygon-key
GMAIL_CREDENTIALS_PATH=config/gmail_credentials.json
GMAIL_TOKEN_PATH=data/gmail_token.json
```

`OPENAI_API_KEY` and Gmail readiness are required before a run can start. `POLYGON_API_KEY` is tracked as a prerequisite because ticker validation and market-data enrichment depend on it.

## 2. Add Gmail OAuth Credentials

Download your Gmail OAuth client credentials JSON from Google Cloud and save it at the path configured by `GMAIL_CREDENTIALS_PATH`.

Default path:

```text
config/gmail_credentials.json
```

## 3. Create the Gmail Token File

Run the local Gmail OAuth helper:

```powershell
$env:PYTHONPATH='src'; python -m email_article_analyzer.cli gmail-auth
```

The command opens a local browser-based OAuth flow, requests Gmail modify access, and writes the resulting token file at `GMAIL_TOKEN_PATH`.

Default path:

```text
data/gmail_token.json
```

Until this token exists, the dashboard and `/api/runs` will block run starts.

## 4. Confirm Source Logins

Before article extraction, confirm browser/session access for premium or gated source websites such as Seeking Alpha, Zacks, and Investing.com. The app reports this as an action-required setup item because those sessions are outside the API configuration.

## 5. Check Readiness

Run:

```powershell
$env:PYTHONPATH='src'; python -m email_article_analyzer.cli setup-status
```

The command prints missing items and next steps. The dashboard shows the same provider readiness checklist above the Start Run button.

## 6. Run the Smoke Check

Before starting a live dashboard session, verify the app can initialize its database and serve the core routes:

```powershell
$env:PYTHONPATH='src'; python scripts/smoke_live_product.py
```

Expected output:

```text
Live product smoke check passed
```

## 7. Start the Dashboard

Run:

```powershell
$env:PYTHONPATH='src'; python -m uvicorn email_article_analyzer.main:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/
```
