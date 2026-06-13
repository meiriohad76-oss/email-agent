# Daily Stock Email Automation - Product Design Review

Date: 2026-06-13
Audience: product owner, human developer, and future AI coding agent
Status: Approved design direction, build-ready review

## 1. Executive Summary

This product is a local stock-article intelligence system. It watches unread Gmail messages from trusted financial senders, extracts the primary article link from each email, captures the article through an authenticated Windows Chrome session when needed, converts the article into clean Markdown, analyzes it with OpenAI, enriches price-target signals with Polygon market data, and stores durable outputs in SQLite.

The v1 user experience is a Raspberry Pi-hosted dashboard. The dashboard handles watchlist upload, ticker validation, run start/stop, source login confirmation, run observability, and review of analyzed articles and signals. Outbound email summaries are deliberately deferred; the dashboard is the primary review surface in v1.

The recommended architecture is a Pi-first orchestrator with a Windows browser helper. The Raspberry Pi owns durable workflow state, the database, external API integrations, and downstream signal access. The Windows helper owns authenticated browser capture using the user's regular Chrome profile.

## 2. Product Goals

The product should:

- Convert unread financial newsletters into structured, reviewable article intelligence.
- Prioritize articles from trusted sources while still analyzing all discovered stock-market articles from those sources.
- Use an uploaded watchlist to distinguish actionable watchlist signals from broader discoveries.
- Produce article-derived structured signals with evidence, confidence, sentiment, stance, and lifecycle state.
- Calculate upside/downside when an article provides a price target and Polygon last-close data is available.
- Provide a local API for another agent to consume unused, unexpired signals.
- Keep a clear audit trail for every run, message, article, analysis, enrichment, and signal.

## 3. Non-Goals for MVP

The MVP should not include:

- Email delivery of summaries.
- Article comment analysis.
- A packaged Windows desktop app.
- Browser extension support.
- PostgreSQL.
- Multi-user authentication.
- URL-level or content-hash deduplication.
- Advanced source-specific parsers beyond basic heuristics.
- Aggregation or merging of multiple signals for the same ticker.
- Encrypted secret storage in the dashboard.
- Automatic model recommendation or cost optimization.

## 4. Key Product Decisions

| Area | Decision |
| --- | --- |
| Article intake | Direct Gmail access. |
| Gmail scope | Unread messages from trusted senders only. |
| Sources | Seeking Alpha, Zacks, Investing.com in v1. |
| Link choice | Analyze only the headline/main article link, usually the first relevant link. |
| Link detection | Email-structure heuristics with fallback to first valid article link. |
| Watchlist | User uploads CSV/Excel. |
| Watchlist mapping | Flexible column mapping; ticker column required. |
| Watchlist replacement | A validated upload replaces the active watchlist. |
| Ticker validation | Validate through Polygon before saving. |
| Invalid upload rows | User chooses whether to reject the upload or accept only valid rows. |
| Article extraction | Direct HTML/text extraction first; PDF is not a default artifact. |
| Stored article artifacts | Cleaned Markdown and structured JSON only. |
| Comments | Skip in v1. |
| LLM provider | OpenAI cloud API. |
| LLM calls | Separate structured extraction and summary calls. |
| Model selection | Dashboard exposes exact model names for extraction and summary. |
| Signals | Watchlist signals plus candidate signals/discoveries. |
| Candidate threshold | Non-watchlist confidence above 70% and at least two supporting evidence snippets. |
| Price data | Polygon API for last close and ticker validation. |
| Price failures | Save signal, mark price missing, queue later enrichment. |
| Signal lifecycle | Keep all records forever; active eligibility is unused and unexpired. |
| Duplicate signals | Keep all article-derived signals separately. |
| Downstream access | Local-network API with API key. |
| Dashboard auth | Simple password in v1. |
| Backend runtime | Raspberry Pi. |
| Browser helper | Windows script/manual startup in v1, packaged app later. |
| Chrome profile | User's regular Chrome profile. |

## 5. User Personas and Jobs

### Product Owner / Investor

Needs to review useful article-derived signals without manually opening every newsletter, copying facts, or re-reading repeated content.

Primary jobs:

- Upload or replace the active watchlist.
- Start a run.
- Confirm source logins when needed.
- Review processing status.
- Review watchlist signals and candidate discoveries.

### Downstream Trading/Decision Agent

Needs a clean API for unused, unexpired article-derived signals.

Primary jobs:

- Fetch available signals.
- Filter by ticker, confidence, type, source, or enrichment status.
- Mark a signal as used so it is not returned again.

### Developer / Future AI Coding Agent

Needs a build-ready design with clear boundaries, data contracts, risks, and testable acceptance criteria.

Primary jobs:

- Implement the pipeline in phases.
- Validate each integration independently.
- Debug runs from durable event logs.
- Extend source parsing, helper packaging, or dashboard features later.

## 6. System Architecture

The system has four runtime parts.

### 6.1 Raspberry Pi Backend

Recommended stack:

- Python
- FastAPI
- SQLite
- Background worker/task queue inside the app for v1
- Environment variables or `.env` for secrets

Responsibilities:

- Serve dashboard APIs and static/frontend assets.
- Run Gmail discovery.
- Maintain run state.
- Store all durable records.
- Coordinate the Windows helper.
- Call OpenAI for extraction and summary.
- Call Polygon for validation and price enrichment.
- Apply Gmail success/failure labels.
- Expose the downstream signal API.

### 6.2 Dashboard

The dashboard is served by the Pi and opened from the user's desktop.

V1 screens:

- Login screen with simple password.
- Run overview and start/stop controls.
- Source login confirmation panel.
- Watchlist upload and column mapping flow.
- Watchlist validation result view.
- Current run progress.
- Run error and retry view.
- Article review list.
- Signal review list.
- Basic settings for model names and API-visible non-secret configuration.

The dashboard should stay operational and dense. It is not a marketing page.

### 6.3 Windows Browser Helper

The helper is a manually started Windows script in v1. It should later be replaceable by a packaged desktop app without changing the backend API contract.

Responsibilities:

- Open login tabs for needed sources.
- Use the user's regular Chrome profile.
- Capture article pages with authenticated session access.
- Extract direct HTML/text when possible.
- Convert article content into clean Markdown.
- Return capture results to the Pi backend.

Implementation spike:

- Test Playwright with a persistent regular Chrome profile.
- Test Chrome remote debugging connection.
- Choose whichever is more reliable for Windows and authenticated sessions.

### 6.4 External Services

- Gmail: unread trusted-source email discovery and labeling.
- OpenAI: structured extraction and 300-word summary generation.
- Polygon: ticker validation and last-close price enrichment.

## 7. End-to-End Workflow

### 7.1 Watchlist Upload

1. User opens dashboard.
2. User uploads CSV or Excel.
3. Backend parses file and returns columns plus sample rows.
4. User maps the ticker column.
5. User may map optional fields such as company name, sector, priority, or notes.
6. Backend validates mapped tickers through Polygon.
7. Dashboard shows valid and invalid rows.
8. User chooses whether to reject and fix the file or accept only valid rows.
9. Backend replaces the active watchlist with the accepted valid rows.

Acceptance criteria:

- No active watchlist replacement occurs before validation and user confirmation.
- Tickers are normalized consistently.
- Invalid rows are visible to the user.
- The system records the upload timestamp and validation source.

### 7.2 Run Startup

1. User starts a run and selects exact OpenAI model names for extraction and summary.
2. Backend searches Gmail for unread messages from trusted sender mappings.
3. Backend skips messages that are already read or labeled `Analyzed`.
4. Backend identifies the headline article link for each candidate message.
5. Backend determines which sources are needed for the run.
6. Dashboard asks the user to log in only to needed sources.

Acceptance criteria:

- No article capture begins before required source confirmations.
- Messages from non-trusted senders are ignored.
- Each candidate message produces at most one headline link in v1.

### 7.3 Login Confirmation

1. Helper opens one login tab per needed source.
2. User logs in manually.
3. User confirms each source separately in the dashboard.
4. Backend marks that source as ready for the run.

Acceptance criteria:

- Source confirmations are scoped to the run.
- A source not needed by the current run is not requested.
- If capture later detects a login wall, the run surfaces a recoverable source-login issue.

### 7.4 Article Capture and Extraction

1. Backend creates capture jobs for each headline link.
2. Windows helper receives jobs from the backend.
3. Helper opens/captures article content using the regular Chrome profile.
4. Helper extracts title, author, publication date, and main article content when available.
5. Helper converts content to clean Markdown.
6. Helper submits capture result to backend.

Clean Markdown should preserve:

- Title.
- Source.
- Publication date.
- Author.
- Main article body.
- Headings.
- Bullet lists.
- Tables when extractable.
- Ticker mentions.
- Analyst ratings.
- Price targets.
- Valuation and financial metrics.
- Evidence-bearing paragraphs.

Clean Markdown should remove:

- Navigation.
- Ads.
- Related article blocks.
- Cookie banners.
- Login prompts.
- Footers.
- Scripts.
- Repeated headers.
- Comments in v1.

Acceptance criteria:

- The stored article artifact is clean Markdown, not raw HTML/PDF.
- Extraction method and failures are recorded.
- Failed capture leaves the Gmail message unread and labeled `Analysis Failed`.

### 7.5 LLM Analysis

The backend performs two OpenAI calls.

#### Structured Extraction Call

Purpose: produce strict JSON for database records and downstream agents.

The output must include:

- Article title.
- Source.
- Source URL.
- Publication date if available.
- Overall theme.
- Article-level summary.
- Market context if present.
- Article-level confidence.
- Mentioned tickers.
- Watchlist stock signals.
- Non-watchlist discoveries.
- Candidate signals when threshold is met.
- Sentiment.
- Stance.
- Catalysts.
- Risks.
- Timeframe.
- Financial details.
- Evidence snippets.
- Confidence.
- Standard note: `Article-derived analysis only, not financial advice.`

#### Summary Call

Purpose: produce a human-facing summary, maximum 300 words, stored in the database.

The summary should be based on:

- Cleaned Markdown.
- Structured extraction JSON.
- Watchlist match status.
- Candidate/discovery status.

Acceptance criteria:

- Structured extraction is schema validated before database write.
- Summary failure does not discard successful structured extraction.
- Model names, token usage, and estimated cost are recorded when available.

### 7.6 Price Enrichment

1. For each signal with an extracted price target, backend requests Polygon last-close data.
2. Backend stores close price, close date, fetched timestamp, and provider.
3. Backend calculates upside/downside percentage.
4. If Polygon fails, backend saves the signal without upside/downside and creates an enrichment retry job.

Acceptance criteria:

- Price enrichment failure does not block signal creation.
- Upside/downside values always record the last-close date used.
- Retry jobs preserve last error and retry count.

### 7.7 Gmail Completion Labels

On successful processing:

- Mark Gmail message read.
- Apply `Analyzed`.
- Remove `Analysis Failed` if present from a previous retry.

On failed processing:

- Keep Gmail message unread.
- Apply `Analysis Failed`.

Acceptance criteria:

- No success label is applied before article processing reaches a durable success state.
- Gmail label failures are surfaced as operational warnings because Gmail and SQLite may diverge.

## 8. Data Model

SQLite is the MVP database. The schema should remain portable enough for PostgreSQL later.

### 8.1 `watchlist_items`

Purpose: active uploaded watchlist.

Suggested fields:

- `id`
- `ticker`
- `normalized_ticker`
- `company_name`
- `sector`
- `priority`
- `notes`
- `source_upload_id`
- `polygon_validation_status`
- `polygon_reference`
- `created_at`
- `updated_at`

### 8.2 `trusted_sources`

Purpose: source definitions.

Suggested fields:

- `id`
- `source_key`
- `display_name`
- `sender_patterns_json`
- `article_domains_json`
- `login_url`
- `enabled`

V1 can seed this table or hardcode equivalent mappings.

### 8.3 `runs`

Purpose: run-level observability.

Suggested fields:

- `id`
- `status`
- `started_at`
- `completed_at`
- `requested_stop_at`
- `extraction_model`
- `summary_model`
- `emails_found_count`
- `emails_skipped_count`
- `articles_analyzed_count`
- `failure_count`
- `signals_created_count`
- `candidate_signals_created_count`
- `discoveries_created_count`
- `price_enrichments_completed_count`
- `openai_prompt_tokens`
- `openai_completion_tokens`
- `estimated_openai_cost`
- `error_summary`

### 8.4 `run_events`

Purpose: durable timeline for debugging.

Suggested fields:

- `id`
- `run_id`
- `event_type`
- `stage`
- `entity_type`
- `entity_id`
- `severity`
- `message`
- `details_json`
- `created_at`

### 8.5 `gmail_messages`

Purpose: processed Gmail unit.

Suggested fields:

- `id`
- `run_id`
- `gmail_message_id`
- `thread_id`
- `sender`
- `subject`
- `received_at`
- `labels_json`
- `was_unread_at_discovery`
- `source_key`
- `processing_status`
- `failure_reason`
- `created_at`
- `updated_at`

Deduplication in v1 is based on Gmail message ID and Gmail state. Future runs ignore messages that are read or labeled `Analyzed`.

### 8.6 `article_links`

Purpose: headline link selected from email.

Suggested fields:

- `id`
- `gmail_message_id`
- `source_key`
- `raw_url`
- `normalized_url`
- `detection_method`
- `detection_confidence`
- `heuristic_notes`
- `created_at`

### 8.7 `articles`

Purpose: extracted article record.

Suggested fields:

- `id`
- `article_link_id`
- `source_key`
- `url`
- `title`
- `author`
- `published_at`
- `cleaned_markdown_path`
- `content_hash`
- `extraction_status`
- `extraction_method`
- `failure_reason`
- `created_at`
- `updated_at`

### 8.8 `analyses`

Purpose: LLM outputs.

Suggested fields:

- `id`
- `article_id`
- `structured_json`
- `summary_300_words`
- `extraction_model`
- `summary_model`
- `extraction_prompt_tokens`
- `extraction_completion_tokens`
- `summary_prompt_tokens`
- `summary_completion_tokens`
- `estimated_cost`
- `article_confidence`
- `created_at`

### 8.9 `signals`

Purpose: actionable article-derived signals.

Suggested fields:

- `id`
- `article_id`
- `analysis_id`
- `ticker`
- `company_name`
- `signal_type`
- `sentiment`
- `stance`
- `theme_summary`
- `confidence`
- `evidence_count`
- `evidence_json`
- `catalysts_json`
- `risks_json`
- `timeframe`
- `price_target`
- `price_target_context`
- `last_close_price`
- `last_close_date`
- `upside_downside_pct`
- `price_enrichment_status`
- `expires_at`
- `used`
- `used_at`
- `used_by`
- `created_at`

Signal types:

- `watchlist`
- `candidate`

Active eligibility:

- `used = false`
- `expires_at > now`
- Enrichment status meets the downstream agent's requested filter.

### 8.10 `financial_details`

Purpose: structured article facts.

Suggested fields:

- `id`
- `article_id`
- `signal_id`
- `ticker`
- `metric`
- `value`
- `period`
- `context`
- `evidence`
- `created_at`

Allowed metric examples:

- `price_target`
- `margin`
- `pe_ratio`
- `revenue`
- `eps`
- `guidance`
- `rating`
- `valuation`
- `other`

### 8.11 `discoveries`

Purpose: non-watchlist ticker findings.

Suggested fields:

- `id`
- `article_id`
- `analysis_id`
- `ticker`
- `company_name`
- `confidence`
- `evidence_count`
- `summary`
- `candidate_signal_id`
- `created_at`

### 8.12 `price_enrichment_jobs`

Purpose: Polygon enrichment retries.

Suggested fields:

- `id`
- `signal_id`
- `ticker`
- `status`
- `attempt_count`
- `last_error`
- `last_attempt_at`
- `next_attempt_at`
- `polygon_response_metadata_json`
- `created_at`
- `updated_at`

## 9. API Contracts

### 9.1 Dashboard APIs

`POST /api/watchlist/upload`

- Input: CSV/Excel file.
- Output: upload ID, detected columns, sample rows.

`POST /api/watchlist/validate`

- Input: upload ID and column mapping.
- Output: valid rows, invalid rows, Polygon validation details.

`POST /api/watchlist/replace`

- Input: upload ID and user decision.
- Output: replacement summary.

`POST /api/runs`

- Input: extraction model, summary model, optional run settings.
- Output: run ID and initial status.

`GET /api/runs/{run_id}`

- Output: status, stage, counts, needed logins, failures, token/cost metrics.

`POST /api/runs/{run_id}/sources/{source}/confirm-login`

- Input: confirmation.
- Output: updated run login readiness.

`POST /api/runs/{run_id}/stop`

- Output: graceful stop requested.

`GET /api/articles`

- Output: article review list with processing status and summary.

`GET /api/signals`

- Output: dashboard signal review list.

### 9.2 Windows Helper APIs

`GET /api/helper/jobs/next`

- Auth: helper token.
- Output: next capture job or no-op.

`POST /api/helper/jobs/{job_id}/started`

- Marks capture job in progress.

`POST /api/helper/jobs/{job_id}/completed`

- Input: extracted title, author, publication date, cleaned Markdown, extraction metadata.

`POST /api/helper/jobs/{job_id}/failed`

- Input: failure stage, error message, source state, retryable flag.

### 9.3 Downstream Agent APIs

All downstream endpoints require API key authentication and should be available only on the local network.

`GET /api/signals/available`

Supported filters:

- `ticker`
- `signal_type`
- `min_confidence`
- `source`
- `enrichment_status`
- `limit`

Returns:

- unused, unexpired signals matching filters.
- evidence snippets.
- price target and upside/downside where available.
- article/source metadata.

`POST /api/signals/{signal_id}/used`

Input:

- `used_by`
- optional consumer metadata.

Effect:

- Marks signal used.
- Sets `used_at`.
- Removes signal from future available queues.

## 10. OpenAI Structured Output Design

The structured extraction should use a strict JSON schema. The implementation should validate model output before writing records.

Recommended top-level shape:

```json
{
  "article": {
    "title": "string or null",
    "source": "string",
    "source_url": "string",
    "published_at": "string or null",
    "author": "string or null",
    "overall_theme": "string",
    "summary": "string",
    "market_context": "string or null",
    "confidence": 0.0
  },
  "mentioned_tickers": [
    {
      "ticker": "string",
      "company_name": "string or null",
      "is_watchlist": true,
      "materiality": "primary | secondary | passing"
    }
  ],
  "signals": [
    {
      "ticker": "string",
      "company_name": "string or null",
      "signal_type": "watchlist | candidate",
      "sentiment": "strong_bullish | bullish | neutral | bearish | strong_bearish",
      "stance": "buy_watch | hold | sell_watch | avoid | unclear",
      "theme_summary": "string",
      "catalysts": ["string"],
      "risks": ["string"],
      "timeframe": "string or null",
      "financial_details": [
        {
          "metric": "price_target | margin | pe_ratio | revenue | eps | guidance | rating | valuation | other",
          "value": "string",
          "period": "string or null",
          "context": "string"
        }
      ],
      "evidence": ["string"],
      "confidence": 0.0
    }
  ],
  "discoveries": [
    {
      "ticker": "string",
      "company_name": "string or null",
      "summary": "string",
      "evidence": ["string"],
      "confidence": 0.0,
      "candidate_signal_recommended": true
    }
  ],
  "actionability_note": "Article-derived analysis only, not financial advice."
}
```

Rules:

- Do not invent tickers, numbers, dates, ratings, or quotes.
- Separate article tone from trading stance.
- Include only materially discussed tickers as signals.
- Use `unclear` when evidence is not strong enough.
- Preserve numerical details exactly as written.
- Candidate signals require non-watchlist confidence above 70% and at least two evidence snippets.
- Watchlist tickers can produce normal signals even when confidence is lower, but low-confidence signals must be visibly marked.

## 11. Dashboard Requirements

### 11.1 Run Dashboard

Must show:

- Current run status.
- Current stage.
- Emails found.
- Emails skipped.
- Links extracted.
- Articles captured.
- Articles analyzed.
- Failures by stage.
- Source login requirements.
- Token usage.
- Estimated OpenAI cost.
- Polygon enrichment status.
- Signals and discoveries created.

### 11.2 Review Dashboard

Most prominent:

- Email/article processing status.
- Per-stock watchlist signals and candidate signals.

Secondary:

- 300-word summaries.
- Article metadata.
- Watchlist match vs non-watchlist discovery status.

### 11.3 Settings

V1 settings may expose:

- Extraction model name.
- Summary model name.
- Trusted sources enabled/disabled if simple.
- Dashboard password setup outside UI through `.env`.
- API configured/not configured indicators.

Secrets should not be shown in clear text.

## 12. Error Handling

| Failure | Behavior |
| --- | --- |
| Gmail discovery failure | Run fails before labels change. |
| No candidate emails | Run completes with zero work. |
| Link detection failure | Message stays unread and gets `Analysis Failed`. |
| Missing source login | Run pauses and requests source confirmation. |
| Browser capture failure | Message stays unread and gets `Analysis Failed`. |
| Markdown extraction failure | Fail unless partial content is usable and clearly marked. |
| OpenAI structured extraction failure | Retry, then fail message if no valid JSON. |
| OpenAI summary failure | Keep structured analysis and mark summary retryable. |
| Polygon validation failure during upload | Show validation error; do not replace watchlist. |
| Polygon price failure during analysis | Save signal, mark price missing, queue enrichment retry. |
| Gmail label update failure | Show operational warning and record event. |
| Helper disconnected | Pause capture jobs and show helper offline state. |

## 13. Observability

Every run should produce a durable event timeline.

Event examples:

- `run_started`
- `gmail_search_started`
- `gmail_message_discovered`
- `headline_link_detected`
- `source_login_required`
- `source_login_confirmed`
- `capture_job_created`
- `capture_started`
- `capture_completed`
- `analysis_started`
- `analysis_completed`
- `signal_created`
- `price_enrichment_failed`
- `gmail_labeled_analyzed`
- `run_completed`

Each event should include:

- timestamp
- run ID
- stage
- entity type and ID
- severity
- human-readable message
- structured JSON details

## 14. Security and Configuration

V1 configuration:

- `.env` or environment variables on the Pi.
- Gmail OAuth credentials.
- OpenAI API key.
- Polygon API key.
- Dashboard password.
- Downstream API key.
- Helper pairing token.

Rules:

- Do not store secrets in SQLite.
- Do not log secrets.
- Do not return secrets through dashboard APIs.
- Keep downstream signal API protected by API key.
- Bind services deliberately and document local-network exposure.
- Treat regular Chrome profile access as sensitive.

## 15. Deployment Model

Raspberry Pi:

- Runs FastAPI backend.
- Serves dashboard.
- Stores SQLite database and artifacts.
- Runs scheduled or user-triggered jobs.

Windows desktop:

- Runs helper script manually in v1.
- Opens Pi dashboard in browser.
- Uses regular Chrome profile for authenticated article access.

Expected startup:

1. Start Pi backend service.
2. Start Windows helper script.
3. Open Pi dashboard from Windows desktop.
4. Upload/confirm watchlist if needed.
5. Start run.
6. Confirm source logins.
7. Monitor and review results.

## 16. Implementation Spikes

Run these before full implementation:

1. Gmail newsletter sampling
   - Confirm sender patterns.
   - Confirm headline-link extraction on real messages.
   - Confirm Gmail labels can be applied as expected.

2. Browser helper reliability
   - Test Playwright persistent profile.
   - Test Chrome remote debugging.
   - Confirm extraction from all three sources.

3. Article cleaning
   - Compare direct HTML extraction libraries.
   - Verify clean Markdown retains financial facts.
   - Confirm comments are excluded.

4. OpenAI structured extraction
   - Validate strict schema output.
   - Test long article chunking if needed.
   - Measure token usage.

5. Polygon integration
   - Validate ticker lookup.
   - Fetch last-close data.
   - Confirm retry behavior for missing/failed data.

6. Raspberry Pi performance
   - Test expected batch size.
   - Monitor memory, CPU, and disk.
   - Measure OpenAI and Polygon latency effects.

## 17. MVP Build Plan

### Phase 1: Foundations

- FastAPI project scaffold.
- SQLite schema and migrations.
- `.env` configuration.
- Basic dashboard password.
- Run/event model.

### Phase 2: Watchlist

- CSV/Excel upload.
- Column mapping UI.
- Polygon validation.
- Active watchlist replacement.

### Phase 3: Gmail Discovery

- Gmail OAuth setup.
- Trusted sender mapping.
- Unread message search.
- Headline-link detection.
- Gmail label management.

### Phase 4: Helper Contract

- Helper job API.
- Manual Windows helper script.
- Browser-control spike result implementation.
- Clean Markdown extraction.

### Phase 5: Analysis

- OpenAI structured extraction.
- Schema validation.
- OpenAI summary call.
- Analysis persistence.

### Phase 6: Signals and Enrichment

- Watchlist signal creation.
- Candidate/discovery creation.
- Polygon last-close enrichment.
- Retry queue.
- Signal lifecycle and expiry.

### Phase 7: Dashboard Review

- Run status view.
- Article review.
- Signal review.
- Failure/retry visibility.
- Token/cost metrics.

### Phase 8: Downstream API

- API key authentication.
- Available signals endpoint.
- Mark-used endpoint.
- Filter support.

## 18. Test Plan

### Unit Tests

- Ticker normalization.
- Watchlist column mapping.
- Polygon validation response handling.
- Gmail trusted sender matching.
- Headline-link heuristic extraction.
- Markdown cleaning.
- OpenAI schema validation.
- Candidate signal threshold logic.
- Upside/downside calculation.
- Signal active eligibility.

### Integration Tests

- Gmail search against test labels/messages.
- Gmail label transitions.
- Polygon validation and close-price lookup.
- OpenAI extraction with fixed fixture content.
- Helper job lifecycle.
- End-to-end run with mocked external services.

### Manual Acceptance Tests

- Upload watchlist with valid tickers.
- Upload watchlist with invalid tickers and accept only valid rows.
- Start run with unread trusted-source message.
- Confirm source login.
- Capture article through helper.
- Store clean Markdown.
- Create watchlist signal.
- Create candidate discovery from non-watchlist ticker.
- Fail Polygon price call and verify enrichment retry.
- Mark successful Gmail message read and `Analyzed`.
- Fail a message and verify unread plus `Analysis Failed`.
- Retry and verify `Analysis Failed` is removed.
- Fetch available signal through downstream API.
- Mark signal used and verify it disappears from available results.

## 19. Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Chrome profile locking | Helper cannot use regular profile reliably. | Spike Playwright vs remote debugging; document startup requirements. |
| Source page layout changes | Extraction breaks. | Keep extraction errors visible; add source-specific tests later. |
| Gmail newsletter format changes | Headline detection picks wrong link. | Store detection method and add dashboard review/failure visibility. |
| OpenAI returns invalid JSON | Analysis cannot be saved. | Strict schema validation and retry. |
| Token cost grows | Runs become expensive. | Clean Markdown, comments skipped, token/cost observability. |
| Polygon outage | Upside/downside unavailable. | Save signal and queue enrichment retry. |
| Gmail labels diverge from DB | Reprocessing or missed messages. | Durable DB status plus operational warnings. |
| Regular Chrome profile access | Sensitive local browser state is involved. | Helper token, local operation, clear operational documentation. |
| Raspberry Pi resource limits | Slow or unstable runs. | Keep Pi orchestration light; browser work remains on Windows. |

## 20. Future Roadmap

### Phase 2: Reliability Hardening

- Better source-specific extraction rules.
- Retry dashboard.
- URL-level deduplication.
- Content-hash deduplication.
- More robust run recovery after crashes.

### Phase 3: Packaged Helper and Better UX

- Packaged Windows helper app.
- Helper auto-update strategy.
- Pairing flow.
- More polished dashboard review.

### Phase 4: Notifications and Analytics

- Batch email digest.
- Optional one-email-per-run summary.
- Historical signal analytics.
- Ticker-level signal history.
- Source performance analytics.

### Phase 5: Scale and Security

- PostgreSQL migration.
- Multi-user login.
- Encrypted secrets settings.
- Role-based dashboard access.
- More advanced downstream-agent permissions.

## 21. Open Questions for Implementation

These are not product blockers, but they should be resolved during spikes:

- Which Windows Chrome control method is more reliable with the regular Chrome profile?
- Which HTML extraction library gives the cleanest Markdown for each source?
- What exact Gmail sender patterns should be used for each source?
- What exact OpenAI model names should be offered at launch?
- What is the expected daily email/article volume?
- What downstream agent fields are mandatory versus optional?

## 22. Final Recommendation

Build the MVP as a Pi-first orchestrator with a Windows browser helper. Keep v1 narrow: unread trusted-source Gmail messages, one headline link per email, clean Markdown storage, OpenAI structured extraction plus summary, Polygon validation/enrichment, SQLite history, dashboard review, and API-key-protected downstream signal access.

This architecture matches the target Raspberry Pi deployment while isolating authenticated browser automation on the Windows desktop where the user's Chrome session already exists. It also creates clean seams for future improvements: packaged helper, email digests, better parser rules, PostgreSQL, and richer signal analytics.
