const state = {
  payload: null,
  companies: [],
  sortKey: "macro_rank",
  sortDirection: "asc",
  selectedTicker: null,
  compare: new Set(),
  details: new Map(),
  bulkStatus: null,
  bulkRefreshInFlight: false,
  bulkPollTimer: null,
  weightDraft: null,
};

const categoryLabels = {
  valuation: "Valuation",
  moat_evidence: "Moat evidence",
  fcf_quality: "FCF quality",
  growth_revisions: "Growth & revisions",
  pricing_power: "Pricing power",
  downside_quality: "Downside quality",
  cross_source_consensus: "Source consensus",
  momentum: "Momentum",
};

const categoryHelp = {
  valuation: "Relative and absolute valuation evidence, including provider grades and available multiples.",
  moat_evidence: "Derived from profitability grade, ROE/ROA/ROI versus industry, and gross/EBIT/FCF margin premiums versus sector. At least three signals are required. This is not a Morningstar moat rating.",
  fcf_quality: "Free-cash-flow strength, conversion, consistency, and supporting cash-flow evidence.",
  growth_revisions: "Revenue and earnings growth combined with estimate direction and analyst revisions.",
  pricing_power: "Derived evidence that the company can sustain price or margins without unacceptable volume loss.",
  downside_quality: "Balance-sheet, profitability, valuation, and target-range evidence relevant to downside resilience.",
  cross_source_consensus: "Agreement among Seeking Alpha, Zacks, and InvestingPro signals.",
  momentum: "Recent price and provider momentum evidence. It is a supporting factor, not a stand-alone thesis.",
};

const sourceIssueLabels = {
  coverage_unavailable: "Provider does not supply",
  access_blocked: "Access blocked",
  parser_gap: "Parser gap",
  temporary: "Temporary outage",
};

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  let payload;
  try { payload = text ? JSON.parse(text) : {}; } catch { payload = { detail: text }; }
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail || payload));
  return payload;
}

function formatNumber(value, digits = 1) {
  return value === null || value === undefined || Number.isNaN(Number(value)) ? "--" : Number(value).toFixed(digits);
}

function formatPercent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function formatDate(value, includeTime = false) {
  if (!value) return "--";
  const normalized = value.includes("T") ? value : `${value.replace(" ", "T")}Z`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit", month: "short", year: "numeric",
    ...(includeTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(date);
}

function statusText(status) {
  return { rank_ready: "Rank ready", partial: "Partial", pending: "Not extracted" }[status] || status;
}

function scoreBand(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "unavailable";
  if (Number(value) >= 75) return "strong";
  if (Number(value) >= 60) return "positive";
  if (Number(value) >= 45) return "neutral";
  return "weak";
}

function sectorTone(sector) {
  return {
    Biotechnology: "biotech",
    "Consumer Staples": "staples",
    Energy: "energy",
    Healthcare: "healthcare",
    Industrials: "industrials",
    Materials: "materials",
    Utilities: "utilities",
  }[sector] || "other";
}

function statusIcon(status) {
  return { rank_ready: "&#10003;", partial: "!", pending: "&#8212;" }[status] || "?";
}

async function initialize() {
  bindControls();
  try {
    const payload = await fetchJson("/api/research/runs");
    const select = document.getElementById("run-select");
    select.replaceChildren();
    payload.runs.forEach((run) => {
      const option = document.createElement("option");
      option.value = run.id;
      option.textContent = `Run ${run.id} - ${run.ticker_count} tickers - ${formatDate(run.completed_at || run.started_at)}`;
      select.appendChild(option);
    });
    if (!payload.runs.length) throw new Error("No research run is available");
    await loadUniverse(Number(select.value));
    await refreshBulkStatus();
    state.bulkPollTimer = window.setInterval(refreshBulkStatus, 5000);
  } catch (error) {
    setStatus(error.message, true);
  }
}

function bindControls() {
  document.getElementById("run-select").addEventListener("change", (event) => loadUniverse(Number(event.target.value)));
  ["search-input", "sector-filter", "status-filter", "coverage-filter"].forEach((id) => {
    document.getElementById(id).addEventListener(id === "search-input" ? "input" : "change", renderTable);
  });
  document.getElementById("clear-filters").addEventListener("click", () => {
    document.getElementById("search-input").value = "";
    document.getElementById("sector-filter").value = "";
    document.getElementById("status-filter").value = "";
    document.getElementById("coverage-filter").value = "0";
    renderTable();
  });
  document.querySelectorAll("th button[data-sort]").forEach((button) => button.addEventListener("click", () => setSort(button.dataset.sort)));
  document.querySelectorAll(".tab-button").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
  document.getElementById("clear-compare").addEventListener("click", () => { state.compare.clear(); updateCompare(); renderTable(); });
  document.getElementById("export-csv").addEventListener("click", exportFilteredCsv);
  document.getElementById("bulk-extract-start").addEventListener("click", startBulkExtraction);
  document.getElementById("bulk-extract-stop").addEventListener("click", stopBulkExtraction);
  document.getElementById("retry-source-issues").addEventListener("click", () => retrySourceIssues(false));
  document.getElementById("retry-access-blocked").addEventListener("click", () => retrySourceIssues(true));
  document.getElementById("weights-open").addEventListener("click", openWeightEditor);
  document.getElementById("weights-close").addEventListener("click", closeWeightEditor);
  document.getElementById("weights-cancel").addEventListener("click", closeWeightEditor);
  document.getElementById("weights-model").addEventListener("change", renderWeightFields);
  document.getElementById("weights-reset").addEventListener("click", resetRecommendedWeights);
  document.getElementById("weights-apply").addEventListener("click", applyWeightConfig);
  document.getElementById("weights-dialog").addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeWeightEditor();
  });
}

async function loadUniverse(runId) {
  setStatus("Loading");
  try {
    state.payload = await fetchJson(`/api/research/universe?run_id=${runId}`);
    state.companies = state.payload.companies;
    state.selectedTicker = null;
    state.details.clear();
    state.compare.clear();
    populateFilters();
    renderSummary();
    renderGuide();
    renderMacro();
    renderTable();
    renderQuality();
    updateCompare();
    renderBulkStatus();
    document.getElementById("detail-pane").innerHTML = '<div class="empty-detail"><strong>Select a company</strong><p>Scores, source evidence, and extraction diagnostics will appear here.</p></div>';
    setStatus(`Run ${runId} loaded`);
  } catch (error) {
    setStatus(error.message, true);
  }
}

function setStatus(text, error = false) {
  const status = document.getElementById("data-status");
  status.textContent = text;
  status.classList.toggle("error", error);
}

function populateFilters() {
  const select = document.getElementById("sector-filter");
  const current = select.value;
  select.innerHTML = '<option value="">All sectors</option>';
  [...new Set(state.companies.map((item) => item.sector))].sort().forEach((sector) => {
    const option = document.createElement("option");
    option.value = sector;
    option.textContent = sector;
    select.appendChild(option);
  });
  select.value = current;
}

function renderSummary() {
  const { summary, methodology, run, macro } = state.payload;
  document.getElementById("kpi-universe").textContent = summary.universe_count;
  document.getElementById("kpi-extracted").textContent = `${summary.companies_with_records}/${summary.universe_count}`;
  document.getElementById("kpi-ready").textContent = summary.sector_model_ready_count;
  document.getElementById("kpi-coverage").textContent = formatPercent(summary.average_score_coverage);
  document.getElementById("kpi-failures").textContent = summary.failed_source_records;
  const macroNote = macro?.active ? ` Macro overlay ${formatDate(macro.as_of)} is active.` : " Macro overlay is unavailable.";
  document.getElementById("method-note").textContent = `${methodology.label}.${macroNote} ${methodology.warning}`;
  document.getElementById("freshness").textContent = `Run ${run.id} completed ${formatDate(run.completed_at || run.started_at, true)} | Macro ${formatDate(macro?.as_of)} | Dashboard refreshed ${formatDate(state.payload.generated_at, true)}`;
  const customWeights = Boolean(methodology.scoring_config?.is_custom);
  document.getElementById("weights-state").textContent = customWeights ? "Custom" : "Recommended";
  document.getElementById("weights-open").classList.toggle("custom", customWeights);
  const universe = Math.max(1, summary.universe_count);
  document.querySelector(".kpi-extracted").style.setProperty("--progress", `${summary.companies_with_records / universe * 100}%`);
  document.querySelector(".kpi-ready").style.setProperty("--progress", `${summary.sector_model_ready_count / universe * 100}%`);
  document.querySelector(".kpi-coverage").style.setProperty("--progress", `${summary.average_score_coverage * 100}%`);
}

function openWeightEditor() {
  const config = state.payload?.methodology?.scoring_config;
  if (!config) return;
  state.weightDraft = JSON.parse(JSON.stringify(config.current));
  const modelSelect = document.getElementById("weights-model");
  modelSelect.replaceChildren();
  const models = [["__generic__", "Generic cross-sector"], ...Object.keys(state.weightDraft.sectors).sort().map((sector) => [sector, sector])];
  models.forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    modelSelect.appendChild(option);
  });
  modelSelect.value = "__generic__";
  document.getElementById("weights-error").textContent = "";
  renderWeightFields();
  document.getElementById("weights-dialog").showModal();
}

function closeWeightEditor() {
  document.getElementById("weights-dialog").close();
  state.weightDraft = null;
}

function selectedWeights(config) {
  const model = document.getElementById("weights-model").value;
  return model === "__generic__" ? config.generic : config.sectors[model];
}

function renderWeightFields() {
  if (!state.weightDraft) return;
  const current = selectedWeights(state.weightDraft);
  const recommended = selectedWeights(state.payload.methodology.scoring_config.recommended);
  document.getElementById("weights-fields").innerHTML = Object.keys(categoryLabels).map((criterion) => `
    <label class="weight-row">
      <span data-tooltip="${escapeHtml(categoryHelp[criterion])}">${escapeHtml(categoryLabels[criterion])}</span>
      <small>Recommended ${formatNumber(recommended[criterion], 0)}%</small>
      <input type="number" min="0" max="100" step="0.5" value="${current[criterion]}" data-criterion="${criterion}" aria-label="${escapeHtml(categoryLabels[criterion])} weight">
    </label>`).join("");
  document.querySelectorAll("#weights-fields input").forEach((input) => input.addEventListener("input", () => {
    selectedWeights(state.weightDraft)[input.dataset.criterion] = Number(input.value);
    updateWeightValidation();
  }));
  updateWeightValidation();
}

function modelTotal(weights) {
  return Object.values(weights).reduce((total, value) => total + Number(value || 0), 0);
}

function allWeightModelsValid() {
  if (!state.weightDraft) return false;
  const models = [state.weightDraft.generic, ...Object.values(state.weightDraft.sectors)];
  return models.every((weights) => Object.values(weights).every((value) => Number.isFinite(Number(value)) && Number(value) >= 0 && Number(value) <= 100) && Math.abs(modelTotal(weights) - 100) < 0.001);
}

function updateWeightValidation() {
  const total = modelTotal(selectedWeights(state.weightDraft));
  const totalElement = document.getElementById("weights-total");
  const selectedValid = Math.abs(total - 100) < 0.001;
  totalElement.textContent = `Total ${formatNumber(total, 1)}%`;
  totalElement.classList.toggle("invalid", !selectedValid);
  document.getElementById("weights-apply").disabled = !allWeightModelsValid();
  document.getElementById("weights-error").textContent = selectedValid ? "" : "The selected model must total 100%.";
}

function resetRecommendedWeights() {
  state.weightDraft = JSON.parse(JSON.stringify(state.payload.methodology.scoring_config.recommended));
  renderWeightFields();
}

async function applyWeightConfig() {
  if (!allWeightModelsValid()) return;
  const applyButton = document.getElementById("weights-apply");
  applyButton.disabled = true;
  setStatus("Applying scoring weights");
  try {
    await fetchJson("/api/research/weights", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.weightDraft),
    });
    const runId = Number(document.getElementById("run-select").value);
    closeWeightEditor();
    await loadUniverse(runId);
  } catch (error) {
    document.getElementById("weights-error").textContent = error.message;
    applyButton.disabled = false;
    setStatus(error.message, true);
  }
}

function formatSigned(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(digits)}`;
}

function adjustmentBand(value) {
  if (Number(value) >= 2) return "positive";
  if (Number(value) <= -2) return "weak";
  return "neutral";
}

function rankMove(value) {
  if (!value) return "";
  const number = Number(value);
  return `<small class="rank-move ${number > 0 ? "up" : "down"}" title="Moved ${Math.abs(number)} places after the macro overlay">${number > 0 ? "&#8593;" : "&#8595;"}${Math.abs(number)}</small>`;
}

function renderMacro() {
  const macro = state.payload?.macro || {};
  const title = document.getElementById("macro-title");
  const subtitle = document.getElementById("macro-subtitle");
  const status = document.getElementById("macro-status");
  const content = document.getElementById("macro-content");
  title.textContent = macro.title || "Macro overlay unavailable";
  subtitle.textContent = macro.active
    ? `As of ${formatDate(macro.as_of)} | ${macro.horizon || "3-5 years"} | ${macro.base_currency || "ILS"} base`
    : (macro.reason || "No active macro regime has been loaded.");
  status.textContent = macro.active ? `${String(macro.confidence || "medium").toUpperCase()} CONFIDENCE` : "NOT APPLIED";
  status.classList.toggle("inactive", !macro.active);
  if (!macro.active) {
    content.innerHTML = `<div class="macro-empty"><strong>The fundamental ranks are unchanged.</strong><p>${escapeHtml(macro.reason || "Refresh the macro research file to activate the overlay.")}</p></div>`;
    return;
  }

  const indicators = (macro.indicators || []).map((indicator) => `
    <div class="macro-indicator ${escapeHtml(indicator.signal || "neutral")}">
      <span>${escapeHtml(indicator.label)}</span><strong>${escapeHtml(indicator.value)}</strong>
      <small>${escapeHtml(indicator.period || "")}</small><p>${escapeHtml(indicator.implication || "")}</p>
    </div>`).join("");
  const scenarios = (macro.scenarios || []).map((scenario) => `
    <div class="scenario-row">
      <div><strong>${escapeHtml(scenario.label)}</strong><p>${escapeHtml(scenario.description)}</p></div>
      <div class="scenario-probability"><span>${Math.round(Number(scenario.probability) * 100)}%</span><i><em style="width:${Math.round(Number(scenario.probability) * 100)}%"></em></i></div>
    </div>`).join("");
  const overlays = [...(macro.sector_overlays || [])]
    .sort((a, b) => Number(b.adjustment) - Number(a.adjustment))
    .map((overlay) => `
      <div class="macro-sector-row">
        <span class="sector-tag ${sectorTone(overlay.sector)}">${escapeHtml(overlay.sector)}</span>
        <strong class="macro-delta ${adjustmentBand(overlay.adjustment)}">${formatSigned(overlay.adjustment)}</strong>
        <div><i><em class="${adjustmentBand(overlay.adjustment)}" style="width:${Math.min(100, Math.abs(Number(overlay.adjustment)) * 18)}%"></em></i><p>${escapeHtml(overlay.rationale)}</p></div>
      </div>`).join("");
  const hedge = macro.hedging || {};
  const rules = (hedge.confirmation_rules || []).map((rule) => `<li>${escapeHtml(rule)}</li>`).join("");
  const sources = (macro.sources || []).map((source) => `
    <a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer"><strong>${escapeHtml(source.publisher)}</strong><span>${escapeHtml(source.title)}</span><small>${formatDate(source.published)}</small></a>`).join("");
  content.innerHTML = `
    <section class="macro-call"><p class="guide-question">Executive call</p><p>${escapeHtml(macro.executive_call || "")}</p></section>
    <section class="macro-section"><div class="macro-section-head"><div><h3>Regime dashboard</h3><p>Current observations and their equity transmission.</p></div></div><div class="macro-indicator-grid">${indicators}</div></section>
    <section class="macro-split">
      <div class="macro-section"><div class="macro-section-head"><div><h3>Scenario probabilities</h3><p>Analyst judgment, not market-implied probabilities.</p></div></div>${scenarios}</div>
      <div class="macro-section"><div class="macro-section-head"><div><h3>Sector score adjustments</h3><p>Points added to the fundamental sector score.</p></div></div>${overlays}</div>
    </section>
    <section class="macro-section hedge-section"><div class="macro-section-head"><div><h3>USD/ILS hedge decision</h3><p>${escapeHtml(hedge.posture || "")}</p></div><strong>${escapeHtml(hedge.research_band || "")}</strong></div><p>${escapeHtml(hedge.current_read || "")}</p><h4>Move toward the upper hedge band only when at least two are true</h4><ol>${rules}</ol><small>${escapeHtml(hedge.limitation || "")}</small></section>
    <section class="macro-section"><div class="macro-section-head"><div><h3>Sources and freshness</h3><p>${escapeHtml(macro.model?.limitations || "")}</p></div></div><div class="macro-sources">${sources}</div></section>`;
}

function renderGuide() {
  const { summary, macro } = state.payload;
  const issues = summary.source_issue_counts || {};
  const recoverable = (issues.parser_gap || 0) + (issues.temporary || 0);
  const blocked = issues.access_blocked || 0;
  const readyShare = summary.universe_count ? summary.sector_model_ready_count / summary.universe_count : 0;
  const trustworthy = readyShare >= 0.9 && summary.average_score_coverage >= 0.85;
  const leaders = [...state.companies]
    .filter((company) => company.sector_model_rank && company.sector_model_rank <= 3)
    .sort((a, b) => a.sector.localeCompare(b.sector) || a.sector_model_rank - b.sector_model_rank);
  const bySector = new Map();
  leaders.forEach((company) => {
    if (!bySector.has(company.sector)) bySector.set(company.sector, []);
    bySector.get(company.sector).push(company);
  });
  const leaderRows = [...bySector.entries()].map(([sector, companies]) => `
    <div class="guide-sector-row">
      <strong>${escapeHtml(sector)}</strong>
      <div>${companies.map((company) => `<button class="guide-company ${scoreBand(company.macro_score)}" data-ticker="${escapeHtml(company.ticker)}" type="button"><span>${escapeHtml(company.ticker)} <b>#${company.sector_model_rank} sector</b></span><small>${formatNumber(company.macro_score)} macro | ${formatSigned(company.macro_adjustment)}</small><i><em style="width:${Math.max(0, Math.min(100, Number(company.macro_score || 0)))}%"></em></i></button>`).join("")}</div>
    </div>`).join("");
  document.getElementById("guide-content").innerHTML = `
    <section class="guide-step ${trustworthy ? "success" : "caution"}">
      <div class="guide-number">1</div>
      <div class="guide-body">
        <p class="guide-question">Can I use this run?</p>
        <h3>${trustworthy ? "Yes, for prioritizing further research" : "Use it cautiously; coverage is still incomplete"}</h3>
        <p>${summary.sector_model_ready_count} of ${summary.universe_count} companies can be ranked within their sector, and ${summary.macro_rank_ready_count || 0} have an active cross-sector macro rank. Average evidence coverage is ${formatPercent(summary.average_score_coverage)}. This supports screening and comparison, not an automatic buy decision.</p>
        <div class="guide-facts"><span><strong>${summary.companies_with_records}/${summary.universe_count}</strong> extracted</span><span><strong>${summary.macro_rank_ready_count || 0}</strong> macro ranked</span><span><strong>${recoverable}</strong> recoverable records</span></div>
      </div>
    </section>
    <section class="guide-step ${macro?.active ? "attention" : "caution"}">
      <div class="guide-number">2</div>
      <div class="guide-body">
        <p class="guide-question">What is the market regime?</p>
        <h3>${escapeHtml(macro?.title || "No current macro overlay")}</h3>
        <p>${escapeHtml(macro?.executive_call || macro?.reason || "Fundamental scores are shown without a macro adjustment.")}</p>
        <div class="guide-facts"><span><strong>${formatDate(macro?.as_of)}</strong> as of</span><span><strong>${macro?.scenarios?.length || 0}</strong> scenarios</span><span><strong>${escapeHtml(String(macro?.confidence || "--"))}</strong> confidence</span></div>
        <button class="guide-link" id="guided-open-macro" type="button">Review regime, scenarios and hedge rules <span aria-hidden="true">&#8594;</span></button>
      </div>
    </section>
    <section class="guide-step">
      <div class="guide-number">3</div>
      <div class="guide-body">
        <p class="guide-question">What does a rank mean?</p>
        <h3>Use macro rank for cross-sector priority and sector rank for peer quality</h3>
        <p>A sector rank of 2/20 means the company scored second among eligible peers on fundamentals. Macro rank compares all eligible companies after the same dated sector adjustment is applied. Coverage shows how much of the fundamental model has real data behind it.</p>
        <button class="guide-link" id="guided-open-universe" type="button">Open the ranked universe <span aria-hidden="true">&#8594;</span></button>
      </div>
    </section>
    <section class="guide-step leaders-step">
      <div class="guide-number">4</div>
      <div class="guide-body">
        <p class="guide-question">Which companies should I inspect first?</p>
        <h3>Start with the top three in each sector</h3>
        <p>Open a ticker to review its factor profile, provider evidence, and source ledger before comparing it with peers.</p>
        <div class="guide-leaders">${leaderRows || '<p>No sector leaders are rank-ready yet.</p>'}</div>
      </div>
    </section>
    <section class="guide-step ${recoverable || blocked ? "attention" : "success"}">
      <div class="guide-number">5</div>
      <div class="guide-body">
        <p class="guide-question">What needs attention now?</p>
        <h3>${recoverable ? `${recoverable} records can be retried` : "No recoverable extraction issues remain"}</h3>
        <p>${issues.coverage_unavailable || 0} requested pages are explicitly not supplied by their provider and ${blocked} pages are access-blocked. Parser and temporary retries preserve every successful record; blocked pages can be retried separately after confirming source sessions are active.</p>
        <div class="guide-actions"><button id="guided-retry-issues" class="primary-action" type="button" ${recoverable ? "" : "disabled"}><span class="button-icon" aria-hidden="true">&#8635;</span> ${recoverable ? `Retry ${recoverable} recoverable records` : "No parser or temporary issues"}</button><button id="guided-retry-blocked" class="quiet-button" type="button" ${blocked ? "" : "disabled"}><span class="button-icon" aria-hidden="true">!</span> Retry ${blocked} blocked pages</button><button id="guided-open-quality" class="quiet-button" type="button">Review data quality <span aria-hidden="true">&#8594;</span></button></div>
      </div>
    </section>`;
  document.getElementById("guided-open-universe").addEventListener("click", () => showView("universe"));
  document.getElementById("guided-open-macro").addEventListener("click", () => showView("macro"));
  document.getElementById("guided-open-quality").addEventListener("click", () => showView("quality"));
  document.getElementById("guided-retry-issues").addEventListener("click", () => retrySourceIssues(false));
  document.getElementById("guided-retry-blocked").addEventListener("click", () => retrySourceIssues(true));
  document.querySelectorAll(".guide-company").forEach((button) => button.addEventListener("click", () => {
    showView("universe");
    loadCompany(button.dataset.ticker);
  }));
}

function filteredCompanies() {
  const search = document.getElementById("search-input").value.trim().toLowerCase();
  const sector = document.getElementById("sector-filter").value;
  const status = document.getElementById("status-filter").value;
  const coverage = Number(document.getElementById("coverage-filter").value || 0);
  return state.companies.filter((company) => {
    const matchesSearch = !search || company.ticker.toLowerCase().includes(search) || company.company.toLowerCase().includes(search);
    return matchesSearch && (!sector || company.sector === sector) && (!status || company.research_status === status) && company.score_coverage >= coverage;
  }).sort(compareValues);
}

function compareValues(a, b) {
  let first = a[state.sortKey];
  let second = b[state.sortKey];
  const missingFirst = first === null || first === undefined;
  const missingSecond = second === null || second === undefined;
  if (missingFirst !== missingSecond) return missingFirst ? 1 : -1;
  if (typeof first === "string") { first = first.toLowerCase(); second = String(second).toLowerCase(); }
  const result = first < second ? -1 : first > second ? 1 : a.ticker.localeCompare(b.ticker);
  return state.sortDirection === "asc" ? result : -result;
}

function setSort(key) {
  if (state.sortKey === key) state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
  else {
    state.sortKey = key;
    state.sortDirection = ["macro_score", "sector_model_score", "composite_score", "score_coverage", "freshest_at"].includes(key) ? "desc" : "asc";
  }
  renderTable();
}

function renderTable() {
  const companies = filteredCompanies();
  const body = document.getElementById("company-table-body");
  body.replaceChildren();
  companies.forEach((company) => {
    const row = document.createElement("tr");
    if (state.selectedTicker === company.ticker) row.classList.add("selected");
    row.innerHTML = `
      <td class="pin-column"><input class="compare-check" type="checkbox" aria-label="Compare ${escapeHtml(company.ticker)}" ${state.compare.has(company.ticker) ? "checked" : ""}></td>
      <td title="Cross-sector rank after the current macro adjustment">${company.macro_rank ? `<span class="rank-value">${company.macro_rank}</span><small class="rank-cohort">/${company.macro_cohort_size}</small>${rankMove(company.macro_rank_change)}` : '<span class="empty-value">--</span>'}</td>
      <td title="Fundamental rank within the eligible sector cohort">${company.sector_model_rank ? `<span class="rank-badge ${company.sector_model_rank <= 3 ? "top" : ""}">#${company.sector_model_rank}</span><small class="rank-cohort">/${company.sector_model_cohort_size}</small>` : '<span class="empty-value">--</span>'}</td>
      <td class="company-cell"><strong>${escapeHtml(company.ticker)}</strong><span title="${escapeHtml(company.company)}">${escapeHtml(company.company)}</span></td>
      <td><span class="sector-tag ${sectorTone(company.sector)}">${escapeHtml(company.sector)}</span></td>
      <td class="numeric" title="Macro score: ${formatNumber(company.sector_model_score)} fundamentals ${formatSigned(company.macro_adjustment)} macro"><span class="score-chip ${scoreBand(company.macro_score)}">${formatNumber(company.macro_score)}</span><small class="macro-inline-delta ${adjustmentBand(company.macro_adjustment)}">${formatSigned(company.macro_adjustment)}</small></td>
      <td class="numeric" title="Sector-weighted fundamental score before macro"><span class="generic-score ${scoreBand(company.sector_model_score)}">${formatNumber(company.sector_model_score)}</span></td>
      <td title="${formatPercent(company.score_coverage)} of generic model weight has usable evidence"><span class="coverage-value">${formatPercent(company.score_coverage)}</span><div class="coverage-track"><div class="coverage-threshold"></div><div class="coverage-fill ${company.score_coverage >= 0.7 ? "ready" : "low"}" style="width:${Math.round(company.score_coverage * 100)}%"></div></div></td>
      <td><span class="status-label ${company.research_status}" title="${company.research_status === "rank_ready" ? "Sufficient evidence for ranking" : company.research_status === "partial" ? "Some evidence exists, but ranking requirements are not met" : "No source records have been extracted yet"}"><i aria-hidden="true">${statusIcon(company.research_status)}</i>${statusText(company.research_status)}</span></td>
      <td class="fresh-cell" title="Newest persisted source record">${formatDate(company.freshest_at)}</td>`;
    row.addEventListener("click", () => loadCompany(company.ticker));
    row.querySelector(".compare-check").addEventListener("click", (event) => {
      event.stopPropagation();
      toggleCompare(company.ticker, event.target.checked);
    });
    body.appendChild(row);
  });
  document.getElementById("visible-count").textContent = `${companies.length} of ${state.companies.length} companies`;
}

async function loadCompany(ticker) {
  state.selectedTicker = ticker;
  renderTable();
  const pane = document.getElementById("detail-pane");
  pane.innerHTML = '<div class="empty-detail"><strong>Loading evidence...</strong></div>';
  try {
    if (!state.details.has(ticker)) {
      const runId = state.payload.run.id;
      state.details.set(ticker, await fetchJson(`/api/research/companies/${encodeURIComponent(ticker)}?run_id=${runId}`));
    }
    renderCompanyDetail(state.details.get(ticker));
  } catch (error) {
    pane.innerHTML = `<div class="empty-detail"><strong>Could not load ${escapeHtml(ticker)}</strong><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function renderCompanyDetail(payload) {
  const { company, score, provider_highlights: highlights, sources } = payload;
  const categories = score ? Object.entries(score.categories) : [];
  const model = state.payload.methodology.sector_model;
  const bulkActive = ["running", "stopping"].includes(state.bulkStatus?.status);
  const evidence = categories.flatMap(([category, value]) => value.evidence.map((item) => ({ category, ...item })));
  document.getElementById("detail-pane").innerHTML = `
    <div class="detail-header">
      <div class="detail-title-row">
        <div><div class="detail-ticker">${escapeHtml(company.ticker)}</div><div class="detail-company">${escapeHtml(company.company)}</div><div class="detail-sector">${escapeHtml(company.sector)} | ${company.record_count} records${company.sector_model_rank ? ` | sector ${company.sector_model_rank}/${company.sector_model_cohort_size}` : ""}${company.macro_rank ? ` | macro ${company.macro_rank}/${company.macro_cohort_size}` : ""}</div></div>
        <div class="detail-score-ring ${scoreBand(company.macro_score)}" style="--score:${Math.max(0, Math.min(100, Number(company.macro_score || 0)))}"><div><strong>${formatNumber(company.macro_score, 0)}</strong><span>MACRO</span></div></div>
      </div>
    </div>
    <div class="warning-callout">Provisional and not backtested. The macro score is for research prioritization, not a buy recommendation. ${escapeHtml(company.sector_model_limitation || "No sector-specific model is available.")}</div>
    <div class="detail-actions">
      <button id="reextract-company" class="primary-action" type="button" data-tooltip="Force a full new paid-source extraction even if this company currently satisfies completion. Existing evidence remains visible until replacement records are saved." ${bulkActive ? "disabled" : ""}><span class="button-icon" aria-hidden="true">&#8635;</span> ${company.record_count ? "Re-extract company" : "Extract company"}</button>
      <span id="reextract-state" class="action-state">${bulkActive ? "Bulk extraction currently owns the browser bridge." : "Requires the connected browser bridge and active paid-source sessions."}</span>
    </div>
    ${renderMacroImpact(company)}
    ${renderSectorModel(company, model)}
    <section class="detail-section"><h3>Factor profile</h3>${renderFactors(categories)}</section>
    <section class="detail-section"><h3>Provider highlights</h3>${renderHighlights(highlights)}</section>
    <section class="detail-section"><h3>Scored evidence</h3>${evidence.length ? evidence.map(renderEvidence).join("") : '<p class="method-note">No sufficient scored evidence yet.</p>'}</section>
    <section class="detail-section"><h3>Source ledger</h3>${sources.length ? sources.map(renderSource).join("") : '<p class="method-note">No source records yet.</p>'}</section>`;
  document.getElementById("reextract-company").addEventListener("click", () => reextractCompany(company));
}

async function reextractCompany(company) {
  if (["running", "stopping"].includes(state.bulkStatus?.status)) {
    setStatus("Stop the bulk extraction before starting an individual company", true);
    return;
  }
  const action = company.record_count ? "re-extract" : "extract";
  const confirmed = window.confirm(
    `Start a full paid-source ${action} cycle for ${company.ticker}? Existing evidence remains visible until replacement records are saved.`,
  );
  if (!confirmed) return;
  const button = document.getElementById("reextract-company");
  const actionState = document.getElementById("reextract-state");
  button.disabled = true;
  button.textContent = "Extracting...";
  actionState.textContent = "Capturing SA, Zacks, InvestingPro, and market-data pages. This can take several minutes.";
  setStatus(`Extracting ${company.ticker}`);
  try {
    const runId = state.payload.run.id;
    const params = new URLSearchParams({ ticker: company.ticker, force: "true", allow_unlisted: "true" });
    const payload = await fetchJson(`/api/runs/${runId}/retry-enrichments?${params.toString()}`, { method: "POST" });
    const result = (payload.results || []).find((item) => item.ticker === company.ticker);
    if (!result || Number(result.attempted || 0) <= 0) {
      throw new Error("Extraction did not start. Verify that the browser bridge is connected and paid-source sessions are active.");
    }
    await loadUniverse(runId);
    await loadCompany(company.ticker);
    setStatus(`${company.ticker}: ${result.saved || 0} saved, ${result.failed || 0} failed`);
  } catch (error) {
    button.disabled = false;
    button.textContent = company.record_count ? "Re-extract company" : "Extract company";
    actionState.textContent = error.message;
    setStatus(error.message, true);
  }
}

async function startBulkExtraction() {
  const pending = state.payload.summary.universe_count - state.payload.summary.companies_with_records;
  if (pending <= 0) return;
  const confirmed = window.confirm(
    `Extract all ${pending} companies that currently have no source records? The job runs one company at a time and may take several hours.`,
  );
  if (!confirmed) return;
  const button = document.getElementById("bulk-extract-start");
  button.disabled = true;
  setStatus("Starting bulk extraction");
  try {
    const runId = state.payload.run.id;
    state.bulkStatus = await fetchJson(`/api/research/bulk-extraction/start?run_id=${runId}`, { method: "POST" });
    renderBulkStatus();
    setStatus(`Bulk extraction started for ${state.bulkStatus.total} companies`);
  } catch (error) {
    button.disabled = false;
    setStatus(error.message, true);
  }
}

async function stopBulkExtraction() {
  const button = document.getElementById("bulk-extract-stop");
  button.disabled = true;
  try {
    state.bulkStatus = await fetchJson("/api/research/bulk-extraction/stop", { method: "POST" });
    renderBulkStatus();
    setStatus("Bulk extraction will stop after the current company");
  } catch (error) {
    button.disabled = false;
    setStatus(error.message, true);
  }
}

async function retrySourceIssues(includeAccessBlocked = false) {
  includeAccessBlocked = includeAccessBlocked === true;
  const issues = state.payload.summary.source_issue_counts || {};
  const issueCount = includeAccessBlocked
    ? (issues.access_blocked || 0)
    : (issues.parser_gap || 0) + (issues.temporary || 0);
  if (issueCount <= 0) return;
  const issueLabel = includeAccessBlocked ? "access-blocked" : "recoverable";
  const confirmed = window.confirm(
    `Retry ${issueCount} ${issueLabel} source records? Successful records remain unchanged.`,
  );
  if (!confirmed) return;
  setStatus("Starting targeted source retry");
  try {
    const runId = state.payload.run.id;
    const params = new URLSearchParams({ run_id: runId });
    if (includeAccessBlocked) params.set("include_access_blocked", "true");
    state.bulkStatus = await fetchJson(`/api/research/source-issues/retry?${params.toString()}`, { method: "POST" });
    renderBulkStatus();
    setStatus(`Retry started for ${state.bulkStatus.total} companies`);
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function refreshBulkStatus() {
  if (state.bulkRefreshInFlight) return;
  state.bulkRefreshInFlight = true;
  const previousStatus = state.bulkStatus?.status;
  try {
    state.bulkStatus = await fetchJson("/api/research/bulk-extraction/status");
    renderBulkStatus();
    if (["running", "stopping"].includes(previousStatus) && ["completed", "stopped"].includes(state.bulkStatus.status)) {
      await loadUniverse(state.payload.run.id);
      setStatus(state.bulkStatus.message);
    }
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    state.bulkRefreshInFlight = false;
  }
}

function renderBulkStatus() {
  if (!state.payload) return;
  const startButton = document.getElementById("bulk-extract-start");
  const stopButton = document.getElementById("bulk-extract-stop");
  const status = document.getElementById("bulk-extract-status");
  const pending = state.payload.summary.universe_count - state.payload.summary.companies_with_records;
  const bulk = state.bulkStatus;
  const active = ["running", "stopping"].includes(bulk?.status);
  const issues = state.payload.summary.source_issue_counts || {};
  const recoverable = (issues.parser_gap || 0) + (issues.temporary || 0);
  startButton.disabled = active || pending <= 0;
  stopButton.hidden = !active;
  stopButton.disabled = bulk?.status === "stopping";
  const individualButton = document.getElementById("reextract-company");
  const individualState = document.getElementById("reextract-state");
  if (individualButton) individualButton.disabled = active;
  if (individualState) individualState.textContent = active
    ? "Bulk extraction currently owns the browser bridge."
    : "Requires the connected browser bridge and active paid-source sessions.";
  const retryButton = document.getElementById("retry-source-issues");
  const blockedButton = document.getElementById("retry-access-blocked");
  const guidedRetryButton = document.getElementById("guided-retry-issues");
  const guidedBlockedButton = document.getElementById("guided-retry-blocked");
  const qualityActionState = document.getElementById("quality-action-state");
  if (retryButton) retryButton.disabled = active || recoverable <= 0;
  if (blockedButton) blockedButton.disabled = active || (issues.access_blocked || 0) <= 0;
  if (guidedRetryButton) guidedRetryButton.disabled = active || recoverable <= 0;
  if (guidedBlockedButton) guidedBlockedButton.disabled = active || (issues.access_blocked || 0) <= 0;
  if (qualityActionState) qualityActionState.textContent = active
    ? `Retry is locked while the extraction job is running${bulk?.current_ticker ? ` (now: ${bulk.current_ticker})` : ""}.`
    : "";
  if (!bulk || bulk.status === "idle") {
    status.textContent = pending ? `${pending} companies have no source records.` : "All universe companies have source records.";
    return;
  }
  if (active) {
    const current = bulk.current_ticker ? ` | Current: ${bulk.current_ticker}` : "";
    status.textContent = bulk.job_type === "source_issue_retry"
      ? `${bulk.processed}/${bulk.total} companies processed | ${bulk.requested_records || recoverable} records requested${current}`
      : `${bulk.processed}/${bulk.total} processed | ${bulk.succeeded} succeeded | ${bulk.failed} failed${current}`;
    return;
  }
  if (bulk.job_type === "source_issue_retry") {
    const stillFailed = Math.max(0, Number(bulk.requested_records || 0) - Number(bulk.saved_records || 0));
    status.textContent = `Retry completed | ${bulk.saved_records || 0} records recovered | ${stillFailed} still need attention`;
    return;
  }
  status.textContent = `${bulk.message} | ${bulk.succeeded} succeeded | ${bulk.failed} failed | ${pending} remain unextracted.`;
}

function renderMacroImpact(company) {
  if (company.macro_score === null || company.macro_score === undefined) {
    return '<section class="detail-section"><h3>Macro overlay</h3><p class="method-note">No active macro score is available for this company.</p></section>';
  }
  return `<section class="detail-section macro-impact-detail"><h3>Macro overlay</h3>
    <div class="score-equation"><span><small>Fundamentals</small><strong>${formatNumber(company.sector_model_score)}</strong></span><i>+</i><span><small>${formatDate(company.macro_overlay_as_of)} regime</small><strong class="${adjustmentBand(company.macro_adjustment)}">${formatSigned(company.macro_adjustment)}</strong></span><i>=</i><span><small>Macro score</small><strong>${formatNumber(company.macro_score)}</strong></span></div>
    <p>${escapeHtml(company.macro_overlay_rationale || "Scenario-weighted sector adjustment.")} Cross-sector rank moved from ${company.fundamental_global_rank || "--"} to ${company.macro_rank || "--"}.</p>
  </section>`;
}

function renderSectorModel(company, model) {
  const weights = model.weights[company.sector];
  if (!weights) return "";
  const active = Object.entries(weights).filter(([, weight]) => weight > 0);
  const benchmarks = model.benchmarks?.[company.sector] || [];
  return `<section class="detail-section"><h3>Sector model</h3>
    <p class="method-note">${escapeHtml(model.version)} | ${formatPercent(company.sector_model_coverage)} coverage | fundamental score ${formatNumber(company.sector_model_score)} | generic diagnostic ${formatNumber(company.composite_score)}${benchmarks.length ? ` | benchmarks ${escapeHtml(benchmarks.join(" / "))}` : ""}</p>
    ${active.map(([name, weight]) => `<div class="factor-row"><span class="factor-label" data-tooltip="${escapeHtml(categoryHelp[name] || "Sector model factor")}">${escapeHtml(categoryLabels[name] || name)}</span><div class="factor-track weight-track"><div class="factor-fill criterion-${name}" style="width:${Math.min(100, weight / 30 * 100)}%"></div></div><span class="factor-score">${weight}%</span></div>`).join("")}
  </section>`;
}

function renderFactors(categories) {
  if (!categories.length) return '<p class="method-note">Extraction pending.</p>';
  return categories.map(([name, category]) => {
    const score = category.score;
    return `<div class="factor-row"><span class="factor-label" data-tooltip="${escapeHtml(categoryHelp[name] || "Scored research factor")}">${escapeHtml(categoryLabels[name] || name)}</span><div class="factor-track"><div class="factor-fill ${scoreBand(score)}" style="width:${score === null ? 0 : score}%"></div></div><span class="factor-score ${scoreBand(score)}">${formatNumber(score, 0)}</span></div>`;
  }).join("");
}

function renderHighlights(highlights) {
  return Object.entries(highlights).map(([provider, items]) => `
    <div class="provider-block"><div class="provider-name">${escapeHtml(provider.replaceAll("_", " "))}</div>
      ${items.length ? `<div class="highlight-grid">${items.map((item) => `<div class="highlight"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(String(item.value))}</strong></div>`).join("")}</div>` : '<p class="method-note">No parsed highlights.</p>'}
    </div>`).join("");
}

function renderEvidence(item) {
  const raw = typeof item.raw === "object" ? JSON.stringify(item.raw) : String(item.raw ?? "--");
  return `<div class="evidence-item"><div class="evidence-head"><span>${escapeHtml(categoryLabels[item.category] || item.category)}: ${escapeHtml(item.label)}</span><strong>${formatNumber(item.score, 0)}</strong></div><div class="evidence-raw">${escapeHtml(raw)}</div></div>`;
}

function renderSource(source) {
  const link = source.source_url ? `<a href="${escapeHtml(source.source_url)}" target="_blank" rel="noreferrer">Open</a>` : "";
  const issue = source.issue_kind ? `<span class="source-issue ${escapeHtml(source.issue_kind)}">${escapeHtml(sourceIssueLabels[source.issue_kind] || source.issue_kind)}</span>` : "";
  return `<div class="source-row"><span class="source-provider">${escapeHtml(source.provider.replaceAll("_", " "))}</span><span class="source-type">${escapeHtml(source.data_type.replaceAll("_", " "))}</span>${link}${issue}${source.failure_reason ? `<span class="source-error">${escapeHtml(source.failure_reason)}</span>` : ""}</div>`;
}

function toggleCompare(ticker, checked) {
  if (checked && state.compare.size >= 6) {
    setStatus("Compare is limited to six companies", true);
    renderTable();
    return;
  }
  checked ? state.compare.add(ticker) : state.compare.delete(ticker);
  setStatus(`Run ${state.payload.run.id} loaded`);
  updateCompare();
}

function updateCompare() {
  document.getElementById("compare-count").textContent = state.compare.size;
  renderCompare();
}

function renderCompare() {
  const selected = [...state.compare].map((ticker) => state.companies.find((item) => item.ticker === ticker)).filter(Boolean);
  const target = document.getElementById("compare-content");
  if (!selected.length) {
    target.innerHTML = '<div class="compare-empty">Pin companies from the universe table to build a factor comparison.</div>';
    return;
  }
  const rows = [
    ["Macro score", (item) => item.macro_score],
    ["Macro percentile", (item) => item.macro_percentile],
    ["Macro adjustment", (item) => item.macro_adjustment],
    ["Rank change", (item) => item.macro_rank_change],
    ["Fundamental sector score", (item) => item.sector_model_score],
    ["Sector percentile", (item) => item.sector_model_percentile],
    ["Generic score", (item) => item.composite_score],
    ["Coverage", (item) => item.score_coverage * 100],
    ...Object.entries(categoryLabels).map(([key, label]) => [label, (item) => item.categories[key]]),
  ];
  target.innerHTML = `<table class="compare-table"><thead><tr><th>Metric</th>${selected.map((item) => `<th>${escapeHtml(item.ticker)}<br><small>${escapeHtml(item.sector)}</small></th>`).join("")}</tr></thead><tbody>${rows.map(([label, getter]) => `<tr><td>${escapeHtml(label)}</td>${selected.map((item) => ["Macro adjustment", "Rank change"].includes(label) ? `<td class="macro-compare ${label === "Macro adjustment" ? adjustmentBand(getter(item)) : Number(getter(item)) >= 0 ? "positive" : "weak"}">${formatSigned(getter(item))}</td>` : heatCell(getter(item))).join("")}</tr>`).join("")}</tbody></table>`;
}

function heatCell(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "<td>--</td>";
  const score = Math.max(0, Math.min(100, Number(value)));
  const red = Math.round(172 - score * 1.05);
  const green = Math.round(65 + score * 1.15);
  const blue = Math.round(55 + score * 0.25);
  return `<td class="heat-score" style="background:rgb(${red},${green},${blue})">${formatNumber(score, 0)}</td>`;
}

function renderQuality() {
  const { summary, sectors } = state.payload;
  const issues = summary.source_issue_counts || {};
  const retryButton = document.getElementById("retry-source-issues");
  const blockedButton = document.getElementById("retry-access-blocked");
  const recoverable = (issues.parser_gap || 0) + (issues.temporary || 0);
  const blocked = issues.access_blocked || 0;
  const extractionActive = ["running", "stopping"].includes(state.bulkStatus?.status);
  const currentTicker = state.bulkStatus?.current_ticker;
  const actionState = document.getElementById("quality-action-state");
  const absence = summary.provider_absence_breakdown || {};
  retryButton.disabled = recoverable <= 0 || extractionActive;
  retryButton.textContent = recoverable ? `Retry ${recoverable} parser or temporary issues` : "No parser or temporary issues";
  blockedButton.disabled = blocked <= 0 || extractionActive;
  blockedButton.textContent = blocked ? `Retry ${blocked} access-blocked pages` : "No access-blocked pages";
  actionState.textContent = extractionActive
    ? `Retry is locked while the extraction job is running${currentTicker ? ` (now: ${currentTicker})` : ""}.`
    : "";
  document.getElementById("quality-summary").innerHTML = `
    <div class="quality-metric success" tabindex="0" data-tooltip="Source records successfully parsed and persisted for the selected run."><i aria-hidden="true">&#10003;</i><span>READY SOURCE RECORDS</span><strong>${summary.ready_source_records}</strong><small>Parsed and persisted</small></div>
    <div class="quality-metric neutral" tabindex="0" data-tooltip="The provider explicitly reports no rating, redirects the ticker to search, or returns a genuine 404 for this page. Retrying the same URL will not create the missing provider product."><i aria-hidden="true">&#8212;</i><span>PROVIDER DOES NOT SUPPLY</span><strong>${issues.coverage_unavailable || 0}</strong><small>Explicit absence, search, or 404</small></div>
    <div class="quality-metric warning" tabindex="0" data-tooltip="The source returned a 403, bot-verification, or other access-block page. Review only when ranking coverage is reduced."><i aria-hidden="true">!</i><span>ACCESS BLOCKED</span><strong>${issues.access_blocked || 0}</strong><small>Authentication or anti-bot</small></div>
    <div class="quality-metric danger" tabindex="0" data-tooltip="A normal source page loaded but the parser could not recognize sufficient structured evidence. These are engineering follow-ups."><i aria-hidden="true">&#10005;</i><span>PARSER GAPS</span><strong>${issues.parser_gap || 0}</strong><small>Needs extractor review</small></div>
    <div class="quality-metric info" tabindex="0" data-tooltip="The source reported maintenance, timeout, or temporary unavailability. These records are candidates for retry."><i aria-hidden="true">&#8635;</i><span>TEMPORARY OUTAGES</span><strong>${issues.temporary || 0}</strong><small>Retry candidates</small></div>
    <div class="quality-metric warning" tabindex="0" data-tooltip="Universe companies with no source records in the selected run. This is a workflow state, not a negative investment assessment."><i aria-hidden="true">?</i><span>UNEXTRACTED COMPANIES</span><strong>${summary.universe_count - summary.companies_with_records}</strong><small>Remain visible in universe</small></div>
    <div class="quality-breakdown"><strong>Why the provider does not supply ${issues.coverage_unavailable || 0}</strong><span>SA rating explicitly unavailable: ${absence.sa_rating_not_supplied || 0}</span><span>Zacks ticker redirects to search: ${absence.zacks_ticker_not_supported || 0}</span><span>Zacks research table not supplied: ${absence.zacks_research_not_supplied || 0}</span><span>InvestingPro page returns 404: ${absence.investing_page_not_found || 0}</span>${absence.other ? `<span>Other: ${absence.other}</span>` : ""}</div>`;
  document.getElementById("sector-progress").innerHTML = sectors.map((sector) => {
    const width = sector.companies ? sector.extracted / sector.companies * 100 : 0;
    const marker = sector.sector_model_cohort_ready ? " *" : "";
    return `<div class="sector-row"><span class="sector-name"><i class="sector-swatch ${sectorTone(sector.sector)}"></i>${escapeHtml(sector.sector)}${marker}</span><div class="sector-track"><div class="sector-fill ${sectorTone(sector.sector)}" style="width:${width}%"></div></div><span class="sector-count">${sector.extracted}/${sector.companies}</span></div>`;
  }).join("");
  const failed = state.companies.filter((item) => item.failed_record_count > 0);
  document.getElementById("failure-list").innerHTML = failed.length ? failed.map((item) => {
    const providers = Object.entries(item.source_counts).filter(([, counts]) => counts.failed).map(([provider, counts]) => `${provider.replaceAll("_", " ")} (${counts.failed})`).join(", ");
    const kinds = Object.entries(item.source_issue_counts || {}).filter(([, count]) => count).map(([kind, count]) => `${sourceIssueLabels[kind] || kind}: ${count}`).join(" | ");
    return `<div class="failure-item"><strong>${escapeHtml(item.ticker)} | ${escapeHtml(providers)}</strong><p>${escapeHtml(kinds || "Unclassified source issue")}</p><button class="failure-action" data-ticker="${escapeHtml(item.ticker)}" type="button">Inspect company</button></div>`;
  }).join("") : '<p class="method-note">No failed source records in this run.</p>';
  document.querySelectorAll(".failure-action").forEach((button) => button.addEventListener("click", () => {
    showView("universe");
    loadCompany(button.dataset.ticker);
  }));
}

function exportFilteredCsv() {
  const params = new URLSearchParams({
    run_id: state.payload.run.id,
    search: document.getElementById("search-input").value.trim(),
    sector: document.getElementById("sector-filter").value,
    status: document.getElementById("status-filter").value,
    min_coverage: document.getElementById("coverage-filter").value || "0",
  });
  const link = document.createElement("a");
  link.href = `/api/research/export.csv?${params.toString()}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function showView(view) {
  document.querySelectorAll(".tab-button").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  document.querySelectorAll(".view-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `${view}-view`));
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[character]));
}

initialize();
