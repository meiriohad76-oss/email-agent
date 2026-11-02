# First-Run Setup

Use this checklist before starting the local Email Article Analyzer dashboard.

## 1. Configure Environment Variables

Create a local `.env` file or set these variables in your shell:

```text
APP_DATABASE_PATH=data/app.db
APP_DASHBOARD_PASSWORD=replace-with-a-long-random-password
OPENAI_API_KEY=your-openai-key
POLYGON_API_KEY=your-polygon-key
GMAIL_CREDENTIALS_PATH=config/gmail_credentials.json
GMAIL_TOKEN_PATH=data/gmail_token.json
```

`OPENAI_API_KEY` and Gmail readiness are required before a run can start. `POLYGON_API_KEY` is tracked as a prerequisite because ticker validation and market-data enrichment depend on it. Default or empty `APP_DASHBOARD_PASSWORD` is accepted only from localhost; set a real password before using LAN, Cloudflare, or Raspberry Pi access.

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

## 8. Install the Chrome Bridge Extension

Install the unpacked Chrome extension in the same Chrome profile where you are
logged in to Seeking Alpha and Zacks:

1. Open `chrome://extensions/`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select the folder printed by:

```powershell
$env:PYTHONPATH='src'; python -m email_article_analyzer.cli browser-extension-path
```

5. Keep Chrome open while running analysis.

For local desktop use, keep the extension backend URL as:

```text
http://127.0.0.1:8000
```

For a Raspberry Pi backend, open the extension options and set **Backend URL**
to the Pi API address:

```text
http://<raspberry-pi-ip>:8000
```

Set **Backend password** to the same value as the Pi's
`APP_DASHBOARD_PASSWORD`.

The dashboard shows **Chrome bridge connected** when the extension can reach the
backend. Runs stay disabled until the bridge is connected.

## Raspberry Pi Backend

On the Pi, start the API with:

```bash
PYTHONPATH=src python -m uvicorn email_article_analyzer.main:app --host 0.0.0.0 --port 8000
```

Do not expose the Pi with `APP_DASHBOARD_PASSWORD=change-me`; the app rejects
network requests until a real password is configured.

From Windows, open:

```text
http://<raspberry-pi-ip>:8000/
```

In this setup, the Pi owns the database, Gmail token, OpenAI key, Polygon key,
and run orchestration. The Windows Chrome extension owns authenticated article
page loading and text extraction.
