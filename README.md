# Email Article Analyzer

Local dashboard for reviewing stock-market newsletter articles from trusted Gmail senders.

## First Run

1. Create a `.env` file from `.env.example`.
2. Set `OPENAI_API_KEY`.
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

Open `http://127.0.0.1:8000/`.

## What Works Now

- Upload CSV/XLSX watchlists.
- Check provider readiness.
- Discover unread trusted-source Gmail messages.
- Extract the headline article link.
- Fetch and store article content when available.
- Fall back to headline-only analysis when content fetching fails.
- Analyze article context with OpenAI structured output.
- Review run events, article links, content status, stance, confidence, evidence, and tickers in the dashboard.
