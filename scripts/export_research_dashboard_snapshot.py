from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
from urllib.parse import quote
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "src" / "email_article_analyzer" / "static"
DEFAULT_OUTPUT = ROOT / "output" / "share" / "investment_research_dashboard_run_51.html"


def _get_json(url: str) -> dict:
    with urlopen(url, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _company_detail(base_url: str, run_id: int, ticker: str) -> tuple[str, dict]:
    url = f"{base_url}/api/research/companies/{quote(ticker)}?run_id={run_id}"
    return ticker, _get_json(url)


def collect_snapshot(base_url: str, run_id: int, max_workers: int = 12) -> dict:
    base_url = base_url.rstrip("/")
    universe = _get_json(f"{base_url}/api/research/universe?run_id={run_id}")
    tickers = [company["ticker"] for company in universe["companies"]]
    details: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_company_detail, base_url, run_id, ticker): ticker
            for ticker in tickers
        }
        for future in as_completed(futures):
            ticker, payload = future.result()
            details[ticker] = payload
    if len(details) != len(tickers):
        raise RuntimeError(f"Expected {len(tickers)} company details, collected {len(details)}")
    run = dict(universe["run"])
    run["ticker_count"] = len(tickers)
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "runs": {"runs": [run]},
        "universe": universe,
        "details": {ticker: details[ticker] for ticker in tickers},
        "bulk_status": {
            "status": "idle",
            "run_id": run_id,
            "total": 0,
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "current_ticker": None,
            "completed_tickers": [],
            "failures": [],
            "message": "Read-only snapshot",
            "job_type": None,
            "requested_records": 0,
            "attempted_records": 0,
            "saved_records": 0,
            "failed_records": 0,
        },
    }


def build_html(snapshot: dict) -> str:
    source_html = (STATIC_DIR / "research.html").read_text(encoding="utf-8")
    source_css = (STATIC_DIR / "research.css").read_text(encoding="utf-8")
    source_js = (STATIC_DIR / "research.js").read_text(encoding="utf-8")
    run_id = snapshot["universe"]["run"]["id"]
    generated = snapshot["exported_at"][:10]

    snapshot_fetch = """
async function fetchJson(url, options = {}) {
  if (window.__RESEARCH_SNAPSHOT__) {
    const rawUrl = String(url);
    // Root-relative URLs resolve beneath the drive letter on file:// pages in
    // Chromium, so preserve the API path before applying URL normalization.
    const requestPath = rawUrl.startsWith("/")
      ? rawUrl.split(/[?#]/, 1)[0]
      : new URL(rawUrl, window.location.href).pathname;
    if (options.method && String(options.method).toUpperCase() !== "GET") {
      throw new Error("This shared dashboard is a read-only snapshot.");
    }
    if (requestPath === "/api/research/runs") return window.__RESEARCH_SNAPSHOT__.runs;
    if (requestPath === "/api/research/universe") return window.__RESEARCH_SNAPSHOT__.universe;
    if (requestPath === "/api/research/bulk-extraction/status") return window.__RESEARCH_SNAPSHOT__.bulk_status;
    const match = requestPath.match(/^\\/api\\/research\\/companies\\/([^/]+)$/);
    if (match) {
      const ticker = decodeURIComponent(match[1]).toUpperCase();
      const detail = window.__RESEARCH_SNAPSHOT__.details[ticker];
      if (!detail) throw new Error("Snapshot company not found: " + ticker);
      return detail;
    }
    throw new Error("Unavailable in read-only snapshot: " + requestPath);
  }
  const response = await fetch(url, options);
  const text = await response.text();
  let payload;
  try { payload = text ? JSON.parse(text) : {}; } catch { payload = { detail: text }; }
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail || payload));
  return payload;
}
"""
    start = source_js.index("async function fetchJson")
    end = source_js.index("\n\nfunction formatNumber", start)
    source_js = source_js[:start] + snapshot_fetch.strip() + source_js[end:]

    snapshot_css = """
.snapshot-notice {
  background: #fff4dc;
  border-bottom: 1px solid #d9bf85;
  color: #5c4516;
  font-size: 12px;
  line-height: 1.45;
  padding: 9px max(20px, calc((100vw - 1480px) / 2));
}
.snapshot-notice strong { color: #2d2514; }
body.snapshot-mode .bulk-extraction-bar,
body.snapshot-mode .quality-actions,
body.snapshot-mode #export-csv,
body.snapshot-mode #weights-open,
body.snapshot-mode #weights-dialog,
body.snapshot-mode .detail-actions { display: none !important; }
body.snapshot-mode #run-select { opacity: .8; pointer-events: none; }
@media print {
  .app-header, .snapshot-notice, .view-tabs, .filter-bar { position: static; }
  body { background: white; }
}
"""
    source_css = source_css + "\n" + snapshot_css
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    inline_script = (
        '<script id="research-snapshot-data" type="application/json">'
        + snapshot_json
        + "</script>\n"
        + "<script>window.__RESEARCH_SNAPSHOT__ = JSON.parse(document.getElementById('research-snapshot-data').textContent);</script>\n"
        + "<script>\n"
        + source_js
        + "\n</script>"
    )
    source_html, css_replacements = re.subn(
        r'<link rel="stylesheet" href="/static/research\.css(?:\?[^\"]*)?">',
        lambda _match: f"<style>\n{source_css}\n</style>",
        source_html,
        count=1,
    )
    source_html, js_replacements = re.subn(
        r'<script src="/static/research\.js(?:\?[^\"]*)?"></script>',
        lambda _match: inline_script,
        source_html,
        count=1,
    )
    if css_replacements != 1 or js_replacements != 1:
        raise RuntimeError(
            "Could not inline the research dashboard assets: "
            f"css={css_replacements}, js={js_replacements}"
        )
    source_html = source_html.replace("<body>", '<body class="snapshot-mode">')
    source_html = source_html.replace(
        '<a class="product-link" href="/">Email Article Analyzer</a>',
        '<span class="product-link">Email Article Analyzer</span>',
    )
    notice = (
        '<div class="snapshot-notice" role="note"><strong>Read-only research snapshot.</strong> '
        f"Run {run_id}, exported {html.escape(generated)}. Interactive filters, comparisons, company evidence, "
        "and source ledgers work offline. Extraction and retry controls are intentionally unavailable. "
        "Provider data remains subject to the sender's subscription and redistribution terms.</div>"
    )
    source_html = source_html.replace("</header>", "</header>\n    " + notice, 1)
    source_html = source_html.replace(
        "<title>Investment Research Dashboard</title>",
        f"<title>Investment Research Dashboard - Run {run_id} Snapshot</title>",
    )
    return source_html


def export_snapshot(base_url: str, run_id: int, output: Path) -> Path:
    snapshot = collect_snapshot(base_url, run_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_html(snapshot), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a self-contained read-only research dashboard")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--run-id", type=int, default=51)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = export_snapshot(args.base_url, args.run_id, args.output)
    print(json.dumps({"output": str(output), "bytes": output.stat().st_size}))


if __name__ == "__main__":
    main()
