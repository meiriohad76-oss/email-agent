# Email Article Analyzer - Windows Install

This package installs the local stock-email article analyzer on a second Windows computer.

## What Is Included

- Python backend and dashboard source code.
- Chrome bridge extension files.
- PowerShell helper scripts:
  - `install.ps1`
  - `run-gmail-auth.ps1`
  - `start-dashboard.ps1`
- `.env.template`

## What Is Not Included

For safety, the package does not include:

- Your `.env` file or API keys.
- Gmail OAuth token.
- Gmail OAuth credentials JSON.
- Existing SQLite database and prior runs.
- Uploaded portfolios/watchlists.

## Prerequisites

Install these on the target Windows computer:

1. Python 3.11 or newer from `https://www.python.org/downloads/windows/`.
2. Google Chrome.
3. A Google OAuth desktop-client credentials JSON for the Gmail account.
4. OpenAI API key.
5. Polygon/Massive API key.
6. Seeking Alpha and Zacks login access in the same Chrome profile.

## Install

1. Extract the ZIP to a simple folder, for example:

```powershell
C:\EmailArticleAnalyzer
```

2. Open PowerShell in that folder.

3. If PowerShell blocks scripts, allow scripts for this session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

4. Run the installer:

```powershell
.\install.ps1
```

If Playwright browser download fails and you only plan to use the Chrome bridge, run:

```powershell
.\install.ps1 -SkipPlaywrightBrowser
```

## Configure API Keys

Open `.env` in Notepad:

```powershell
notepad .env
```

Set:

```text
OPENAI_API_KEY=your-openai-key
POLYGON_API_KEY=your-polygon-key
APP_DASHBOARD_PASSWORD=a-long-random-password
```

Keep these paths unless you know you need different ones:

```text
GMAIL_CREDENTIALS_PATH=config/gmail_credentials.json
GMAIL_TOKEN_PATH=data/gmail_token.json
APP_DATABASE_PATH=data/app.db
```

## Add Gmail Credentials

Copy your Google OAuth desktop-client credentials file to:

```text
config\gmail_credentials.json
```

Then run:

```powershell
.\run-gmail-auth.ps1
```

A browser will open for Google login and consent. After success, the token is saved locally under `data\gmail_token.json`.

## Install Chrome Bridge Extension

Use the normal Chrome profile where you are logged in to Seeking Alpha and Zacks.

1. Open Chrome.
2. Go to:

```text
chrome://extensions/
```

3. Enable **Developer mode**.
4. Click **Load unpacked**.
5. Select this folder inside the extracted package:

```text
browser-extension
```

6. Open the extension options/details if needed and set:

```text
Backend URL: http://127.0.0.1:8000
Backend password: the APP_DASHBOARD_PASSWORD from .env
```

## Start The App

Run:

```powershell
.\start-dashboard.ps1
```

Open:

```text
http://127.0.0.1:8000/
```

If the dashboard asks for authentication, use any username and the `APP_DASHBOARD_PASSWORD` as the password.

## First Use Checklist

1. Confirm dashboard says API/providers are ready.
2. Confirm dashboard says Chrome bridge connected.
3. Open Seeking Alpha and Zacks in Chrome and log in.
4. Upload portfolio/watchlist CSV/XLSX.
5. Start a small test run before a large run.
6. Export a PDF report from the completed run.

## Troubleshooting

Check setup status:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m email_article_analyzer.cli setup-status
```

Common issues:

- `OPENAI_API_KEY missing`: edit `.env`.
- `POLYGON_API_KEY missing`: edit `.env`.
- `gmail missing`: run `.\run-gmail-auth.ps1`.
- `Chrome bridge not connected`: make sure Chrome is open and the extension Backend URL/password match `.env`.
- PDF export fails: install Google Chrome or Microsoft Edge.

## Moving Existing Data

By default this package starts fresh. To move prior runs/watchlists from another machine, copy that machine's:

```text
data\app.db
```

into the new machine's `data` folder while the app is stopped.

