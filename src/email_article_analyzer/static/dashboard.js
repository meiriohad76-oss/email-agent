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
  writeResult("run-lookup-result", "Loading run...");
  try {
    const payload = await fetchJson(`/api/runs/${runId}`);
    writeResult("run-lookup-result", payload);
  } catch (error) {
    writeResult("run-lookup-result", error.message);
  }
});

document.getElementById("recent-runs-list").addEventListener("click", async (event) => {
  const row = event.target.closest("[data-run-id]");
  if (!row) {
    return;
  }
  const runId = row.dataset.runId;
  document.getElementById("run-id").value = runId;
  writeResult("run-lookup-result", "Loading run...");
  try {
    const payload = await fetchJson(`/api/runs/${runId}`);
    writeResult("run-lookup-result", payload);
  } catch (error) {
    writeResult("run-lookup-result", error.message);
  }
});

checkHealth();
refreshRecentRuns();
