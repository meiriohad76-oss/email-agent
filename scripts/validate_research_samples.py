from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from email_article_analyzer.research_metrics import (  # noqa: E402
    parse_investing_research,
    parse_seeking_alpha_research,
    parse_zacks_detailed_estimates,
)


SA_PAGES = {
    "sa_valuation": "valuation",
    "sa_growth": "growth",
    "sa_profitability": "profitability",
    "sa_momentum": "momentum",
    "sa_estimates": "estimates",
    "sa_revisions": "revisions",
    "sa_peers": "peers",
    "sa_income_statement": "income_statement",
    "sa_cash_flow": "cash_flow_statement",
}
INVESTING_PAGES = {
    "investing_overview": "overview",
    "investing_financial_summary": "financial_summary",
    "investing_ratios": "ratios",
    "investing_cash_flow": "cash_flow_statement",
    "investing_forecast": "forecast",
    "investing_ownership": "ownership",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate structured parsing of captured research samples.")
    parser.add_argument("ticker", nargs="?", default="XOM")
    args = parser.parse_args()
    ticker = args.ticker.upper()
    sample_dir = ROOT / "data" / "research_samples" / ticker
    results = []
    for name, page_type in SA_PAGES.items():
        results.append(_parse_file(sample_dir, name, parse_seeking_alpha_research, ticker, page_type))
    for name, page_type in INVESTING_PAGES.items():
        results.append(_parse_file(sample_dir, name, parse_investing_research, ticker, page_type))
    results.append(
        _parse_file(sample_dir, "zacks_detailed_estimates", parse_zacks_detailed_estimates, ticker, None)
    )
    print(json.dumps(results, indent=2))
    return 0 if all(result["parsed"] for result in results) else 1


def _parse_file(sample_dir, name, parser, ticker, page_type):
    path = sample_dir / f"{name}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    text = payload.get("extracted_text", "")
    records = parser(ticker, page_type, text) if page_type else parser(ticker, text)
    record = records[0] if records else {}
    return {
        "sample": name,
        "parsed": bool(records),
        "data_type": record.get("rating_type"),
        "top_level_fields": sorted(record),
        "metric_count": _metric_count(record),
    }


def _metric_count(record):
    total = 0
    for key in (
        "eps_estimates",
        "revenue_estimates",
        "sales_estimates",
        "earnings_estimates",
        "revision_agreement",
        "consensus_trend",
    ):
        value = record.get(key)
        if isinstance(value, (list, dict)):
            total += len(value)
    if total:
        return total
    for key in ("metrics", "rows", "composition", "valuation_models", "peer_symbols"):
        value = record.get(key)
        if isinstance(value, (list, dict)):
            return len(value)
    categories = record.get("categories")
    if isinstance(categories, dict):
        return sum(len(value) for value in categories.values())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
