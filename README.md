# Email Article Analyzer

Local stock-research platform for reviewing trusted newsletter articles and ranking
global listed companies with normalized evidence from market-data and research
providers.

## Investment Research Dashboard

The `/research` workspace provides a source-auditable workflow for:

- enriching a global equity universe from Seeking Alpha, Zacks, Investing.com,
  InvestingPro, and Polygon;
- distinguishing genuine provider non-coverage from authentication, transient,
  and parser failures;
- scoring valuation, moat evidence, free-cash-flow quality, growth and revisions,
  pricing power, downside quality, cross-source consensus, and momentum;
- applying configurable sector-specific factor weights and ranking each company
  against eligible sector peers;
- applying a dated, probability-weighted macro-regime overlay to sector scores and
  showing the resulting cross-sector rank changes;
- inspecting evidence, coverage, freshness, and provider diagnostics for every
  company; and
- exporting a read-only standalone HTML snapshot for offline sharing.

The sector models and macro overlay are transparent sensitivity frameworks, not
predictions or automated investment advice. The UI exposes their assumptions,
coverage requirements, and limitations. Recommended sector weights are defined in
`src/email_article_analyzer/sector_scoring.py` and remain editable in the dashboard.

The active macro view is loaded from `data/macro_regime_current.json`. Copy
`docs/macro-regime.example.json` there and replace the example scenarios with a
dated, sourced analysis. Scenario probabilities must sum to `1.0`; stale regimes
are automatically disabled.

## First Run

1. Create a `.env` file from `.env.example`.
2. Set `OPENAI_API_KEY` and replace `APP_DASHBOARD_PASSWORD` with a long password.
3. Save Gmail OAuth client credentials at `GMAIL_CREDENTIALS_PATH`.
4. Run Gmail auth:

```powershell
$env:PYTHONPATH='src'; python -m email_article_analyzer.cli gmail-auth
```

5. Check readiness:

```powershell
$env:PYTHONPATH='src'; python -m email_article_analyzer.cli setup-status
```

6. Run the local smoke check:

```powershell
$env:PYTHONPATH='src'; python scripts/smoke_live_product.py
```

7. Start the dashboard:

```powershell
$env:PYTHONPATH='src'; python -m uvicorn email_article_analyzer.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/` for article analysis or
`http://127.0.0.1:8000/research` for investment research.

8. Install the local Chrome bridge extension in the same Chrome profile you use for
   Seeking Alpha and Zacks:

   - Open `chrome://extensions/`.
   - Enable **Developer mode**.
   - Click **Load unpacked**.
   - Select the folder printed by:

```powershell
$env:PYTHONPATH='src'; python -m email_article_analyzer.cli browser-extension-path
```

   - Keep Chrome open while running analysis.
   - For local desktop use, keep the extension backend URL as
     `http://127.0.0.1:8000`.
   - If you set `APP_DASHBOARD_PASSWORD`, enter the same value in the extension
     **Backend password** field.

The dashboard shows **Chrome bridge connected** when the extension is polling the
local app. Runs are disabled until the bridge is connected, because source
articles must open in the user's logged-in Chrome session.

## Raspberry Pi Backend

For the end-state always-on deployment, run the backend on the Raspberry Pi and
keep the Chrome bridge extension on the Windows Chrome profile where you are
logged in to Seeking Alpha and Zacks.

Start the API on the Pi with a network-facing host:

```bash
PYTHONPATH=src python -m uvicorn email_article_analyzer.main:app --host 0.0.0.0 --port 8000
```

Network-facing dashboard access requires `APP_DASHBOARD_PASSWORD` to be set to
a real password. The default/empty password is accepted only from localhost.

Open the dashboard from Windows at:

```text
http://<raspberry-pi-ip>:8000/
```

Then open the Chrome extension options and set **Backend URL** to:

```text
http://<raspberry-pi-ip>:8000
```

Also set **Backend password** to the Pi's `APP_DASHBOARD_PASSWORD`.

With that setup, the Pi scans Gmail and runs analysis, while the Windows Chrome
extension opens authenticated article tabs in your normal browser and sends the
extracted article text back to the Pi.

## What Works Now

- Upload CSV/XLSX watchlists.
- Check provider readiness.
- Discover unread trusted-source Gmail messages.
- Extract the headline article link.
- Open source-domain articles in the user's normal Chrome via the local bridge extension.
- Fetch and store article content from the user Chrome tab.
- Skip source analysis when the Chrome bridge is not connected instead of launching a separate app Chrome profile.
- Analyze article context with OpenAI structured output.
- Review run events, article links, content status, stance, confidence, evidence, and tickers in the dashboard.

## Export a Research Snapshot

Create a self-contained, read-only HTML file from a completed research run:

```powershell
$env:PYTHONPATH='src'; python scripts/export_research_dashboard_snapshot.py --run-id 80 --output output/share/investment_research_dashboard.html
```

The snapshot embeds the selected run's dashboard payload. Extraction and retry
controls are intentionally disabled in exported files.

## Data and Subscription Boundaries

This repository contains extractor logic, normalization rules, scoring models,
dashboard code, tests, and synthetic parser fixtures. It does not contain API
keys, browser cookies, OAuth tokens, local databases, live paid-page captures,
current macro conclusions, generated spreadsheets, or exported dashboards.

Users must supply their own provider subscriptions and authenticated browser
sessions. Access and use of provider data remain subject to each provider's terms,
including restrictions on redistribution.
