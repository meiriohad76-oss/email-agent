const DEFAULT_API_BASE = "http://127.0.0.1:8000";

function normalizeApiBase(value) {
  return String(value || DEFAULT_API_BASE).trim().replace(/\/+$/, "");
}

async function loadOptions() {
  const stored = await chrome.storage.local.get({
    apiBase: DEFAULT_API_BASE,
    backendPassword: "",
  });
  document.getElementById("api-base").value = normalizeApiBase(stored.apiBase);
  document.getElementById("backend-password").value = stored.backendPassword || "";
}

async function saveOptions() {
  const input = document.getElementById("api-base");
  const passwordInput = document.getElementById("backend-password");
  const status = document.getElementById("status");
  const apiBase = normalizeApiBase(input.value);
  try {
    const url = new URL(apiBase);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      throw new Error("Backend URL must start with http:// or https://");
    }
    await chrome.storage.local.set({
      apiBase,
      backendPassword: passwordInput.value.trim(),
    });
    status.textContent = "Saved.";
  } catch (error) {
    status.textContent = error.message;
  }
}

document.getElementById("save-button").addEventListener("click", saveOptions);
loadOptions();
