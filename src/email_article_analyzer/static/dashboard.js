const formatJson = (value) => JSON.stringify(value, null, 2);

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
    throw new Error(payload.detail || formatJson(payload));
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
    list.append(item);
  });
}

async function refreshProviderStatus() {
  const list = document.getElementById("provider-status-list");
  try {
    const payload = await fetchJson("/api/status/providers");
    renderProviderStatus(payload);
  } catch (error) {
    const item = document.createElement("div");
    item.className = "provider-status-item missing";
    item.textContent = error.message;
    list.replaceChildren(item);
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

    row.append(title, meta, link);
    list.append(row);
  });
}

function renderRunDetail(payload) {
  const run = payload.run;
  const counts = payload.counts || {};
  const events = payload.events || [];
  const articles = payload.articles || [];
  const summary = document.getElementById("run-detail-summary");
  summary.replaceChildren(
    metricCard("Run", `#${run.id}`),
    metricCard("Status", run.status),
    metricCard("Emails", counts.gmail_messages ?? 0),
    metricCard("Links", counts.article_links ?? 0),
    metricCard("Extraction model", run.extraction_model),
    metricCard("Summary model", run.summary_model),
  );
  renderSourceLoginWarnings(events);
  renderArticleRows(articles);
  renderEventTimeline(events);
  setRunDetailStatus(`Loaded run #${run.id}`);
}

function renderRecentRuns(runs) {
  const list = document.getElementById("recent-runs-list");
  list.replaceChildren();
  if (!runs.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No runs have been recorded yet.";
    list.append(empty);
    return;
  }
  runs.forEach((run) => {
    const row = document.createElement("button");
    row.className = "run-row";
    row.type = "button";
    row.dataset.runId = run.id;

    const messages = run.counts?.gmail_messages ?? 0;
    const links = run.counts?.article_links ?? 0;
    [
      ["run-id", `#${run.id}`],
      ["run-status", run.status],
      ["", `${messages} emails`],
      ["", `${links} links`],
      ["", run.started_at],
    ].forEach(([className, text]) => {
      const cell = document.createElement("span");
      cell.textContent = text;
      if (className) {
        cell.className = className;
      }
      row.append(cell);
    });
    list.append(row);
  });
}

async function refreshRecentRuns() {
  try {
    const payload = await fetchJson("/api/runs");
    renderRecentRuns(payload.runs || []);
  } catch (error) {
    const list = document.getElementById("recent-runs-list");
    const empty = document.createElement("p");
    empty.className = "empty-state error-text";
    empty.textContent = error.message;
    list.replaceChildren(empty);
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

document.getElementById("run-start-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const body = {
    extraction_model: form.get("extraction_model") || null,
    summary_model: form.get("summary_model") || null,
  };
  writeResult("run-start-result", "Starting run...");
  try {
    const payload = await fetchJson("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    writeResult("run-start-result", payload);
    await refreshRecentRuns();
  } catch (error) {
    writeResult("run-start-result", error.message);
  }
});

document.getElementById("run-lookup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const runId = document.getElementById("run-id").value;
  setRunDetailStatus("Loading run...");
  try {
    const payload = await fetchJson(`/api/runs/${runId}`);
    renderRunDetail(payload);
  } catch (error) {
    setRunDetailStatus(error.message, true);
  }
});

document.getElementById("recent-runs-list").addEventListener("click", async (event) => {
  const row = event.target.closest("[data-run-id]");
  if (!row) {
    return;
  }
  const runId = row.dataset.runId;
  document.getElementById("run-id").value = runId;
  setRunDetailStatus("Loading run...");
  try {
    const payload = await fetchJson(`/api/runs/${runId}`);
    renderRunDetail(payload);
  } catch (error) {
    setRunDetailStatus(error.message, true);
  }
});

checkHealth();
refreshProviderStatus();
refreshRecentRuns();
