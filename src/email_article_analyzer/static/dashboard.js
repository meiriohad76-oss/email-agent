const formatJson = (value) => JSON.stringify(value, null, 2);
let latestProviderStatusPayload = { providers: {} };
let browserBridgeConnected = false;

function formatApiError(payload) {
  if (typeof payload.detail === "string") {
    return payload.detail;
  }
  if (payload.detail) {
    return formatJson(payload.detail);
  }
  return formatJson(payload);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  let payload;
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    payload = { raw: text };
  }
  if (!response.ok) {
    throw new Error(formatApiError(payload));
  }
  return payload;
}

function writeResult(id, value) {
  document.getElementById(id).textContent =
    typeof value === "string" ? value : formatJson(value);
}

function renderProviderStatus(payload) {
  const list = document.getElementById("provider-status-list");
  list.replaceChildren();
  Object.entries(payload.providers || {}).forEach(([key, provider]) => {
    const item = document.createElement("div");
    item.className = `provider-status-item ${provider.status}`;
    const name = document.createElement("strong");
    name.textContent = key.replace("_", " ");
    const status = document.createElement("span");
    status.textContent = provider.status;
    item.append(name, status);
    (provider.details || []).forEach((detail) => {
      const note = document.createElement("small");
      note.textContent = detail;
      item.append(note);
    });
    (provider.setup_steps || []).forEach((setupStep) => {
      const step = document.createElement("small");
      step.className = "provider-setup-step";
      step.textContent = setupStep;
      item.append(step);
    });
    list.append(item);
  });
}

function updateRunStartAvailability(payload) {
  latestProviderStatusPayload = payload;
  const providers = payload.providers || {};
  const essentialProviderKeys = ["openai", "gmail"];
  const missingEssentialProviders = essentialProviderKeys.filter(
    (key) => providers[key]?.status !== "ready",
  );
  const startButton = document.getElementById("start-run-button");
  const message = document.getElementById("run-readiness-message");
  if (!browserBridgeConnected) {
    startButton.disabled = true;
    message.textContent = "Start disabled until the Chrome bridge extension is connected.";
    message.classList.add("error-text");
    return;
  }
  if (!missingEssentialProviders.length) {
    startButton.disabled = false;
    message.textContent = "Essential providers are ready.";
    message.classList.remove("error-text");
    return;
  }
  startButton.disabled = true;
  message.textContent = `Start disabled until essential provider setup is ready: ${missingEssentialProviders.join(", ")}`;
  message.classList.add("error-text");
}

async function refreshProviderStatus() {
  const list = document.getElementById("provider-status-list");
  try {
    const payload = await fetchJson("/api/status/providers");
    renderProviderStatus(payload);
    updateRunStartAvailability(payload);
  } catch (error) {
    const item = document.createElement("div");
    item.className = "provider-status-item missing";
    item.textContent = error.message;
    list.replaceChildren(item);
    updateRunStartAvailability({ providers: {} });
  }
}

async function refreshBrowserBridgeStatus() {
  const status = document.getElementById("browser-bridge-status");
  try {
    const payload = await fetchJson("/api/browser-tasks/status");
    browserBridgeConnected = payload.status === "connected";
    status.textContent = browserBridgeConnected
      ? "Chrome bridge connected."
      : "Chrome bridge not connected. Install/enable the local Chrome extension before running analysis.";
    status.classList.toggle("error-text", !browserBridgeConnected);
  } catch (error) {
    browserBridgeConnected = false;
    status.textContent = `Chrome bridge unavailable: ${error.message}`;
    status.classList.add("error-text");
  }
  updateRunStartAvailability(latestProviderStatusPayload);
}

function openSourceLogin(source, url) {
  let tab = null;
  try {
    tab = window.open("about:blank", "_blank");
    if (tab) {
      tab.location.href = url;
      tab.focus();
    }
  } catch {
    tab = null;
  }
  writeResult("run-start-result", {
    status: tab ? "opened" : "blocked",
    opened_source: source,
    url,
    next: tab
      ? "Login tab opened."
      : `Chrome blocked the popup. Copy/open this URL manually: ${url}`,
  });
}

async function confirmSourceLogins() {
  writeResult("run-start-result", "Confirming source logins...");
  try {
    const payload = await fetchJson("/api/source-logins/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sources: ["seeking_alpha", "zacks", "investing"] }),
    });
    writeResult("run-start-result", payload);
    await refreshProviderStatus();
  } catch (error) {
    writeResult("run-start-result", error.message);
  }
}

async function stopCurrentRun() {
  writeResult("run-start-result", "Requesting stop...");
  try {
    const payload = await fetchJson("/api/runs/stop-current", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    writeResult("run-start-result", payload);
    await refreshRecentRuns();
  } catch (error) {
    writeResult("run-start-result", error.message);
  }
}

function exportRunReport() {
  const runId = document.getElementById("run-id").value;
  if (!runId) {
    setRunDetailStatus("Enter or load a run before exporting a report.", true);
    return;
  }
  window.location.href = `/api/runs/${runId}/report.pdf`;
}

async function retryRunEnrichments() {
  const runId = document.getElementById("run-id").value;
  if (!runId) {
    setRunDetailStatus("Enter or load a run before retrying enrichments.", true);
    return;
  }
  setRunDetailStatus(`Retrying ticker enrichments for run #${runId}...`);
  try {
    const payload = await fetchJson(`/api/runs/${runId}/retry-enrichments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    writeResult("run-start-result", payload);
    await loadRunDetail(runId, `Retried enrichments for run #${runId}.`);
  } catch (error) {
    setRunDetailStatus(error.message, true);
    writeResult("run-start-result", error.message);
  }
}

async function retryGmailMarks() {
  const runId = document.getElementById("run-id").value;
  if (!runId) {
    setRunDetailStatus("Enter or load a run before retrying Gmail marks.", true);
    return;
  }
  setRunDetailStatus(`Retrying Gmail marks for run #${runId}...`);
  try {
    const payload = await fetchJson(`/api/runs/${runId}/retry-gmail-marks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    writeResult("run-start-result", payload);
    await loadRunDetail(
      runId,
      `Retried Gmail marks for run #${runId}: ${payload.repaired} repaired, ${payload.failed} failed.`,
    );
  } catch (error) {
    setRunDetailStatus(error.message, true);
    writeResult("run-start-result", error.message);
  }
}

async function deleteRun(runId) {
  const confirmed = window.confirm(
    `Delete run #${runId}? This will mark its Gmail messages unread, remove analysis labels, and delete this run's database records.`,
  );
  if (!confirmed) {
    return;
  }
  setRunDetailStatus(`Deleting run #${runId}...`);
  try {
    const payload = await fetchJson(`/api/runs/${runId}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
    });
    writeResult("run-start-result", payload);
    if (document.getElementById("run-id").value === String(runId)) {
      document.getElementById("run-id").value = "";
      document.getElementById("run-detail-summary").replaceChildren();
      document.getElementById("source-login-warning-list").replaceChildren();
      document.getElementById("run-enrichment-list").replaceChildren();
      document.getElementById("run-article-list").replaceChildren();
      document.getElementById("run-event-timeline").replaceChildren();
    }
    setRunDetailStatus(`Deleted run #${runId}.`);
    await refreshRecentRuns();
  } catch (error) {
    setRunDetailStatus(error.message, true);
    writeResult("run-start-result", error.message);
  }
}

async function forceStopRun(runId) {
  const confirmed = window.confirm(
    `Mark run #${runId} as stopped? Use this only when the run is stale and no browser or worker is still progressing.`,
  );
  if (!confirmed) {
    return;
  }
  setRunDetailStatus(`Marking run #${runId} stopped...`);
  try {
    const payload = await fetchJson(`/api/runs/${runId}/force-stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    writeResult("run-start-result", payload);
    await refreshRecentRuns();
    if (document.getElementById("run-id").value === String(runId)) {
      await loadRunDetail(runId, `Marked run #${runId} stopped.`);
    }
  } catch (error) {
    setRunDetailStatus(error.message, true);
    writeResult("run-start-result", error.message);
  }
}

function setRunDetailStatus(message, isError = false) {
  const status = document.getElementById("run-detail-status");
  status.textContent = message;
  status.classList.toggle("error-text", isError);
}

function metricCard(label, value) {
  const card = document.createElement("div");
  card.className = "metric-card";
  const cardLabel = document.createElement("span");
  cardLabel.className = "metric-label";
  cardLabel.textContent = label;
  const cardValue = document.createElement("strong");
  cardValue.textContent = value ?? "-";
  card.append(cardLabel, cardValue);
  return card;
}

function formatRunTimestamp(value) {
  return value || "-";
}

function formatContentStatus(status) {
  if (status === "email_fallback") {
    return "email fallback";
  }
  return status || "not fetched";
}

function renderSourceLoginWarnings(events) {
  const list = document.getElementById("source-login-warning-list");
  list.replaceChildren();
  const warnings = events.filter((event) => event.event_type === "source_login_needed");
  if (!warnings.length) {
    return;
  }
  const heading = document.createElement("h3");
  heading.textContent = "Source login needed";
  list.append(heading);
  warnings.forEach((event) => {
    const item = document.createElement("div");
    item.className = "warning-item";
    item.textContent = event.message;
    list.append(item);
  });
}

function renderRunAlerts(alerts) {
  const list = document.getElementById("source-login-warning-list");
  (alerts || []).forEach((alert) => {
    const item = document.createElement("div");
    item.className = `warning-item run-alert ${alert.severity || "warning"}`;
    const title = document.createElement("strong");
    title.textContent = alert.title || "Run alert";
    const message = document.createElement("div");
    message.textContent = alert.message || "";
    item.append(title, message);
    if (alert.next) {
      const next = document.createElement("small");
      next.textContent = alert.next;
      item.append(next);
    }
    list.append(item);
  });
}

function renderEventTimeline(events) {
  const timeline = document.getElementById("run-event-timeline");
  timeline.replaceChildren();
  if (!events.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No events recorded for this run.";
    timeline.append(empty);
    return;
  }
  events.forEach((event) => {
    const row = document.createElement("div");
    row.className = "event-timeline-row";
    const meta = document.createElement("div");
    meta.className = "event-meta";
    meta.textContent = `${event.created_at} - ${event.stage} - ${event.severity}`;
    const message = document.createElement("div");
    message.className = "event-message";
    message.textContent = event.message;
    row.append(meta, message);
    timeline.append(row);
  });
}

function renderArticleRows(articles) {
  const list = document.getElementById("run-article-list");
  list.replaceChildren();
  const heading = document.createElement("h3");
  heading.textContent = "Discovered articles";
  list.append(heading);
  if (!articles.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No article links discovered for this run.";
    list.append(empty);
    return;
  }
  articles.forEach((article) => {
    const row = document.createElement("div");
    row.className = "article-row";

    const title = document.createElement("div");
    title.className = "article-title";
    title.textContent = article.subject;

    const meta = document.createElement("div");
    meta.className = "article-meta";
    meta.textContent = [
      article.source_key,
      article.sender,
      article.message_status,
      `${Math.round((article.detection_confidence ?? 0) * 100)}% confidence`,
      article.detection_method,
    ].join(" - ");

    const link = document.createElement("a");
    link.href = article.normalized_url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = article.normalized_url;

    const contentStatus = document.createElement("div");
    contentStatus.className = `article-fetch-status ${article.content?.fetch_status || "missing"}`;
    if (article.content) {
      const contentParts = [`Content: ${formatContentStatus(article.content.fetch_status)}`];
      if (article.content.title) {
        contentParts.push(article.content.title);
      }
      if (article.content.text_char_count) {
        contentParts.push(`${article.content.text_char_count} chars`);
      }
      if (article.content.failure_reason) {
        contentParts.push(article.content.failure_reason);
      }
      contentStatus.textContent = contentParts.join(" - ");
    } else {
      contentStatus.textContent = "Content: not fetched";
    }

    const analysis = document.createElement("div");
    analysis.className = "article-analysis";
    if (article.analysis) {
      const analysisHeader = document.createElement("div");
      analysisHeader.className = "article-analysis-header";
      const confidence = Math.round((article.analysis.confidence ?? 0) * 100);
      analysisHeader.textContent = [
        article.analysis.stance,
        article.analysis.sentiment,
        `Recommendation: ${article.analysis.recommendation || "unclear"}`,
        `${confidence}% confidence`,
        article.analysis.model,
      ].filter(Boolean).join(" - ");

      const summary = document.createElement("p");
      summary.textContent = article.analysis.summary;

      const tickers = document.createElement("div");
      tickers.className = "article-tickers";
      tickers.append("Tickers: ");
      const tickerDetails = article.analysis.mentioned_ticker_details || [];
      if (tickerDetails.length) {
        tickerDetails.forEach((tickerDetail) => {
          const chip = document.createElement("span");
          chip.className = `ticker-chip ${tickerDetail.in_portfolio ? "in-portfolio" : "not-in-portfolio"}`;
          chip.textContent = tickerDetail.in_portfolio
            ? `${tickerDetail.ticker} - portfolio`
            : `${tickerDetail.ticker} - not portfolio`;
          tickers.append(chip);
        });
      } else {
        tickers.append((article.analysis.mentioned_tickers || []).join(", ") || "-");
      }

      const evidence = document.createElement("ul");
      evidence.className = "article-evidence";
      (article.analysis.supporting_evidence || []).forEach((item) => {
        const evidenceItem = document.createElement("li");
        evidenceItem.textContent = item;
        evidence.append(evidenceItem);
      });

      const actionable = document.createElement("div");
      actionable.className = "article-actionable";
      const priceTargets = article.analysis.price_targets || [];
      const actionableData = article.analysis.actionable_data || [];
      if (priceTargets.length || actionableData.length) {
        actionable.append(actionableLine("Price targets", priceTargets.map(formatPriceTarget).join("; ") || "-"));
        actionableData.forEach((item) => {
          actionable.append(
            actionableLine(
              item.ticker || "Ticker",
              [
                item.recommendation ? `Recommendation: ${item.recommendation}` : null,
                item.sentiment ? `Sentiment: ${item.sentiment}` : null,
                item.timeframe ? `Timeframe: ${item.timeframe}` : null,
                (item.catalysts || []).length ? `Catalysts: ${(item.catalysts || []).join(", ")}` : null,
                (item.risks || []).length ? `Risks: ${(item.risks || []).join(", ")}` : null,
                (item.financial_details || []).length
                  ? `Details: ${(item.financial_details || []).join(", ")}`
                  : null,
              ].filter(Boolean).join(" | "),
            ),
          );
        });
      }

      analysis.append(analysisHeader, summary, tickers, actionable, evidence);
    } else {
      analysis.textContent = "Analysis: pending";
    }

    row.append(title, meta, link, contentStatus, analysis);
    list.append(row);
  });
}

function renderTickerEnrichments(enrichments) {
  const list = document.getElementById("run-enrichment-list");
  list.replaceChildren();
  const heading = document.createElement("h3");
  heading.textContent = "Ticker enrichments";
  list.append(heading);
  if (!enrichments.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No Polygon, Seeking Alpha, Zacks, or InvestingPro enrichment snapshots recorded for this run.";
    list.append(empty);
    return;
  }
  const polygonLastCloseByTicker = new Map();
  enrichments.forEach((enrichment) => {
    const data = enrichment.data || {};
    if (
      enrichment.provider === "polygon" &&
      enrichment.data_type === "previous_close" &&
      data.last_close !== undefined &&
      data.last_close !== null
    ) {
      polygonLastCloseByTicker.set(enrichment.ticker, Number(data.last_close));
    }
  });
  enrichments.forEach((enrichment) => {
    const row = document.createElement("div");
    row.className = `enrichment-row ${enrichment.status || "unknown"}`;

    const title = document.createElement("div");
    title.className = "enrichment-title";
    title.textContent = [
      enrichment.ticker,
      enrichment.provider,
      enrichment.data_type,
      enrichment.status,
    ].filter(Boolean).join(" - ");

    const value = document.createElement("div");
    value.className = "enrichment-value";
    value.textContent = formatTickerEnrichment(enrichment, polygonLastCloseByTicker);

    row.append(title, value);
    if (enrichment.source_url) {
      const link = document.createElement("a");
      link.href = enrichment.source_url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = enrichment.source_url;
      row.append(link);
    }
    list.append(row);
  });
}

function formatTickerEnrichment(enrichment, polygonLastCloseByTicker = new Map()) {
  if (enrichment.status === "failed") {
    return `Failed: ${enrichment.failure_reason || "unknown error"}`;
  }
  const data = enrichment.data || {};
  if (data.last_close !== undefined && data.last_close !== null) {
    return `Last close: ${data.last_close}`;
  }
  if (data.rating_type) {
    const parts = [
      data.rating ? `Rating: ${data.rating}` : null,
      data.score !== undefined && data.score !== null ? `Score: ${data.score}` : null,
      data.price_target !== undefined && data.price_target !== null
        ? formatTargetWithPolygonBaseline(enrichment.ticker, data, polygonLastCloseByTicker)
        : null,
      data.source_text ? `Evidence: ${data.source_text}` : null,
    ];
    return parts.filter(Boolean).join(" | ") || "Ready";
  }
  if (enrichment.provider === "investing_pro") {
    return formatInvestingProEnrichment(data);
  }
  return JSON.stringify(data);
}

function formatInvestingProEnrichment(data) {
  const parts = [];
  if (data.rating) {
    parts.push(`Rating: ${data.rating}`);
  }
  if (data.financial_health) {
    parts.push(`Health: ${data.financial_health}`);
  }
  if (data.fair_value !== undefined && data.fair_value !== null) {
    parts.push(`Fair value: ${data.fair_value}`);
  }
  if (data.fair_value_upside_pct !== undefined && data.fair_value_upside_pct !== null) {
    parts.push(`Fair value upside: ${Number(data.fair_value_upside_pct).toFixed(1)}%`);
  } else if (data.fair_value_upside) {
    parts.push(`Fair value upside: ${data.fair_value_upside}`);
  }
  if (data.analyst_target_average !== undefined && data.analyst_target_average !== null) {
    parts.push(`Analyst target avg: ${data.analyst_target_average}`);
  } else if (data.analyst_price_target) {
    parts.push(`Analyst target: ${data.analyst_price_target}`);
  }
  if (data.rating_count !== undefined && data.rating_count !== null) {
    parts.push(`Ratings: ${data.rating_count}`);
  }
  if (data.metrics) {
    ["P/E Ratio", "Revenue", "EPS", "Beta"].forEach((label) => {
      if (data.metrics[label] !== undefined && data.metrics[label] !== null) {
        parts.push(`${label}: ${data.metrics[label]}`);
      }
    });
  }
  return parts.length ? parts.join(" | ") : JSON.stringify(data);
}

function formatTargetWithPolygonBaseline(ticker, data, polygonLastCloseByTicker) {
  const currency = data.currency || "USD";
  const target = Number(data.price_target);
  const parts = [`Target: ${currency} ${data.price_target}`];
  const lastClose = polygonLastCloseByTicker.get(ticker);
  if (Number.isFinite(target) && Number.isFinite(lastClose) && lastClose !== 0) {
    const normalizedUpside = ((target - lastClose) / lastClose) * 100;
    parts.push(`Polygon upside: ${normalizedUpside >= 0 ? "+" : ""}${normalizedUpside.toFixed(1)}%`);
  } else {
    parts.push("Polygon upside: needs Polygon close");
  }
  if (data.source_reported_upside_pct !== undefined && data.source_reported_upside_pct !== null) {
    parts.push(`Source upside: ${Number(data.source_reported_upside_pct).toFixed(2)}%`);
  }
  return parts.join(" | ");
}

function actionableLine(label, value) {
  const line = document.createElement("div");
  line.className = "article-actionable-line";
  const strong = document.createElement("strong");
  strong.textContent = `${label}: `;
  line.append(strong, value);
  return line;
}

function formatPriceTarget(target) {
  const price = target.target_price === null || target.target_price === undefined
    ? "not specified"
    : `${target.currency || ""} ${target.target_price}`.trim();
  return `${target.ticker || "Ticker"} ${price} ${target.timeframe || ""}`.trim();
}

function renderRunDetail(payload) {
  const run = payload.run;
  const counts = payload.counts || {};
  const events = payload.events || [];
  const alerts = payload.alerts || [];
  const articles = payload.articles || [];
  const enrichments = payload.ticker_enrichments || [];
  const summary = document.getElementById("run-detail-summary");
  summary.replaceChildren(
    metricCard("Run", `#${run.id}`),
    metricCard("Status", run.status),
    metricCard("Started", formatRunTimestamp(run.started_at)),
    metricCard("Completed", formatRunTimestamp(run.completed_at)),
    metricCard("Emails", counts.gmail_messages ?? 0),
    metricCard("Links", counts.article_links ?? 0),
    metricCard("Precheck model", run.extraction_model),
    metricCard("Article analysis model", run.summary_model),
    metricCard("Report synthesis model", "gpt-5.6-sol"),
  );
  renderSourceLoginWarnings(events);
  renderRunAlerts(alerts);
  renderTickerEnrichments(enrichments);
  renderArticleRows(articles);
  renderEventTimeline(events);
  setRunDetailStatus(
    alerts.length ? `${alerts[0].title}: ${alerts[0].next || alerts[0].message}` : `Loaded run #${run.id}`,
    alerts.length,
  );
}

function renderRecentRuns(runs, alerts = []) {
  const list = document.getElementById("recent-runs-list");
  list.replaceChildren();
  (alerts || []).forEach((alert) => {
    const item = document.createElement("div");
    item.className = `warning-item run-alert ${alert.severity || "warning"}`;
    const title = document.createElement("strong");
    title.textContent = alert.title || "Run alert";
    const message = document.createElement("div");
    message.textContent = alert.message || "";
    item.append(title, message);
    if (alert.next) {
      const next = document.createElement("small");
      next.textContent = alert.next;
      item.append(next);
    }
    list.append(item);
  });
  if (!runs.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No runs have been recorded yet.";
    list.append(empty);
    return;
  }
  runs.forEach((run) => {
    const row = document.createElement("div");
    row.className = "run-row";
    row.role = "button";
    row.tabIndex = 0;
    row.dataset.runId = run.id;

    const messages = run.counts?.gmail_messages ?? 0;
    const links = run.counts?.article_links ?? 0;
    const main = document.createElement("div");
    main.className = "run-row-main";
    [
      ["run-id", `#${run.id}`],
      ["run-status", run.status],
      ["", `Started ${formatRunTimestamp(run.started_at)}`],
      ["", `Completed ${formatRunTimestamp(run.completed_at)}`],
      ["", `${messages} emails`],
      ["", `${links} links`],
      ["", `Precheck ${run.extraction_model || "-"}`],
      ["", `Analysis ${run.summary_model || "-"}`],
    ].forEach(([className, text]) => {
      const cell = document.createElement("span");
      cell.textContent = text;
      if (className) {
        cell.className = className;
      }
      main.append(cell);
    });
    (run.alerts || []).forEach((alert) => {
      const cell = document.createElement("span");
      cell.className = `run-alert-chip ${alert.severity || "warning"}`;
      cell.textContent = alert.title || "Run alert";
      main.append(cell);
    });

    const actions = document.createElement("div");
    actions.className = "run-row-actions";
    const pdfButton = document.createElement("button");
    pdfButton.type = "button";
    pdfButton.className = "secondary-button compact-button";
    pdfButton.textContent = "PDF";
    pdfButton.setAttribute("data-run-pdf-id", run.id);
    if (run.status === "running") {
      const forceStopButton = document.createElement("button");
      forceStopButton.type = "button";
      forceStopButton.className = "secondary-button compact-button";
      forceStopButton.textContent = "Mark stopped";
      forceStopButton.setAttribute("data-run-force-stop-id", run.id);
      actions.append(forceStopButton);
    }
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "danger-button compact-button";
    deleteButton.textContent = "Delete";
    deleteButton.setAttribute("data-run-delete-id", run.id);
    actions.append(pdfButton, deleteButton);

    row.append(main, actions);
    list.append(row);
  });
}

async function refreshRecentRuns() {
  try {
    const payload = await fetchJson("/api/runs");
    renderRecentRuns(payload.runs || [], payload.alerts || []);
  } catch (error) {
    const list = document.getElementById("recent-runs-list");
    const empty = document.createElement("p");
    empty.className = "empty-state error-text";
    empty.textContent = error.message;
    list.replaceChildren(empty);
  }
}

async function loadRunDetail(runId, successMessage = null) {
  document.getElementById("run-id").value = runId;
  setRunDetailStatus("Loading run...");
  const payload = await fetchJson(`/api/runs/${runId}`);
  renderRunDetail(payload);
  if (successMessage) {
    setRunDetailStatus(successMessage);
  }
}

async function checkHealth() {
  const pill = document.getElementById("health-status");
  try {
    const payload = await fetchJson("/api/health");
    pill.textContent = `API ${payload.status}`;
    pill.classList.add("ok");
  } catch (error) {
    pill.textContent = "API unavailable";
    pill.classList.add("error");
  }
}

document.getElementById("watchlist-upload").addEventListener("submit", async (event) => {
  event.preventDefault();
  const fileInput = document.getElementById("watchlist-file");
  if (!fileInput.files.length) {
    writeResult("watchlist-result", "Choose a CSV or XLSX file.");
    return;
  }
  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  writeResult("watchlist-result", "Uploading...");
  try {
    const payload = await fetchJson("/api/watchlist/upload", {
      method: "POST",
      body: formData,
    });
    writeResult("watchlist-result", payload);
  } catch (error) {
    writeResult("watchlist-result", error.message);
  }
});

document
  .getElementById("source-login-open-sa-button")
  .addEventListener("click", () => {
    openSourceLogin("seeking_alpha", "https://seekingalpha.com/");
  });

document
  .getElementById("source-login-open-zacks-button")
  .addEventListener("click", () => {
    openSourceLogin("zacks", "https://www.zacks.com/login");
  });

document
  .getElementById("source-login-open-investing-button")
  .addEventListener("click", () => {
    openSourceLogin("investing", "https://www.investing.com/");
  });

document
  .getElementById("source-login-confirm-button")
  .addEventListener("click", confirmSourceLogins);

document
  .getElementById("stop-run-button")
  .addEventListener("click", stopCurrentRun);

document
  .getElementById("export-report-button")
  .addEventListener("click", exportRunReport);

document
  .getElementById("retry-enrichments-button")
  .addEventListener("click", retryRunEnrichments);

document
  .getElementById("retry-gmail-marks-button")
  .addEventListener("click", retryGmailMarks);

document.getElementById("run-start-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (document.getElementById("start-run-button").disabled) {
    writeResult(
      "run-start-result",
      browserBridgeConnected
        ? "Start disabled until essential provider setup is ready."
        : "Start disabled until the Chrome bridge extension is connected.",
    );
    return;
  }
  const form = new FormData(event.currentTarget);
  const extractionModel = String(form.get("extraction_model") || "").trim();
  const summaryModel = String(form.get("summary_model") || "").trim();
  const body = {
    extraction_model: extractionModel || null,
    summary_model: summaryModel || null,
  };
  writeResult("run-start-result", "Starting run...");
  const progressRefresh = window.setInterval(refreshRecentRuns, 5000);
  try {
    const payload = await fetchJson("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    writeResult("run-start-result", payload);
    if (payload.run_id) {
      const alert = (payload.alerts || [])[0];
      await loadRunDetail(
        payload.run_id,
        alert
          ? `${alert.title}: ${alert.next || alert.message}`
          : `Run completed. Loaded details for run #${payload.run_id}.`,
      );
    }
    await refreshRecentRuns();
  } catch (error) {
    writeResult("run-start-result", error.message);
  } finally {
    window.clearInterval(progressRefresh);
    await refreshRecentRuns();
  }
});

document.getElementById("run-lookup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const runId = document.getElementById("run-id").value;
  try {
    await loadRunDetail(runId);
  } catch (error) {
    setRunDetailStatus(error.message, true);
  }
});

document.getElementById("recent-runs-list").addEventListener("click", async (event) => {
  const pdfButton = event.target.closest("[data-run-pdf-id]");
  if (pdfButton) {
    event.stopPropagation();
    window.location.href = `/api/runs/${pdfButton.getAttribute("data-run-pdf-id")}/report.pdf`;
    return;
  }
  const deleteButton = event.target.closest("[data-run-delete-id]");
  if (deleteButton) {
    event.stopPropagation();
    await deleteRun(deleteButton.getAttribute("data-run-delete-id"));
    return;
  }
  const forceStopButton = event.target.closest("[data-run-force-stop-id]");
  if (forceStopButton) {
    event.stopPropagation();
    await forceStopRun(forceStopButton.getAttribute("data-run-force-stop-id"));
    return;
  }
  const row = event.target.closest("[data-run-id]");
  if (!row) {
    return;
  }
  const runId = row.dataset.runId;
  try {
    await loadRunDetail(runId);
  } catch (error) {
    setRunDetailStatus(error.message, true);
  }
});

document.getElementById("recent-runs-list").addEventListener("keydown", async (event) => {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  const row = event.target.closest("[data-run-id]");
  if (!row || event.target !== row) {
    return;
  }
  event.preventDefault();
  try {
    await loadRunDetail(row.dataset.runId);
  } catch (error) {
    setRunDetailStatus(error.message, true);
  }
});

checkHealth();
refreshProviderStatus();
refreshBrowserBridgeStatus();
refreshRecentRuns();
window.setInterval(refreshBrowserBridgeStatus, 5000);
