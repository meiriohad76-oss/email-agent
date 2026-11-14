from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import httpx


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def research_urls(ticker: str, investing_slug: str) -> dict[str, str]:
    investing_base = f"https://www.investing.com/equities/{investing_slug}"
    return {
        "sa_valuation": f"https://seekingalpha.com/symbol/{ticker}/valuation/metrics",
        "sa_growth": f"https://seekingalpha.com/symbol/{ticker}/growth",
        "sa_profitability": f"https://seekingalpha.com/symbol/{ticker}/profitability",
        "sa_momentum": f"https://seekingalpha.com/symbol/{ticker}/momentum/performance",
        "sa_estimates": f"https://seekingalpha.com/symbol/{ticker}/earnings/estimates",
        "sa_revisions": f"https://seekingalpha.com/symbol/{ticker}/earnings/revisions",
        "sa_peers": f"https://seekingalpha.com/symbol/{ticker}/peers/comparison",
        "sa_income_statement": f"https://seekingalpha.com/symbol/{ticker}/income-statement",
        "sa_cash_flow": f"https://seekingalpha.com/symbol/{ticker}/cash-flow-statement",
        "sa_news": f"https://seekingalpha.com/symbol/{ticker}/news",
        "sa_analysis": f"https://seekingalpha.com/symbol/{ticker}/analysis",
        "sa_options": f"https://seekingalpha.com/symbol/{ticker}/options",
        "zacks_style_scores": f"https://www.zacks.com/stock/quote/{ticker}/style-scores",
        "zacks_detailed_estimates": f"https://www.zacks.com/stock/quote/{ticker}/detailed-earning-estimates",
        "zacks_insider_transactions": f"https://www.zacks.com/stock/research/{ticker}/insider-transactions",
        "zacks_options_chain": f"https://www.zacks.com/stock/quote/{ticker}/options-chain",
        "zacks_greeks_montage": f"https://www.zacks.com/stock/quote/{ticker}/greeks-montage",
        "zacks_key_metrics": f"https://www.zacks.com/stock/quote/{ticker}/key-company-metrics",
        "zacks_industry_comparison": f"https://www.zacks.com/stock/quote/{ticker}/industry-comparison",
        "investing_overview": investing_base,
        "investing_financial_summary": f"{investing_base}-financial-summary",
        "investing_ratios": f"{investing_base}-ratios",
        "investing_cash_flow": f"{investing_base}-cash-flow",
        "investing_forecast": f"{investing_base}-consensus-estimates",
        "investing_ownership": f"{investing_base}-ownership",
        "investing_news": f"{investing_base}-news",
        "investing_analysis": f"{investing_base}-opinion",
        "investing_options": f"{investing_base}-options",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture authenticated SA/Zacks research samples.")
    parser.add_argument("ticker", nargs="?", default="AAPL")
    parser.add_argument("--investing-slug", default="apple-computer-inc")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=240.0)
    args = parser.parse_args()

    ticker = args.ticker.strip().upper()
    output_dir = ROOT / "data" / "research_samples" / ticker
    output_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=httpx.Timeout(args.timeout + 30, connect=10.0)) as client:
        for name, url in research_urls(ticker, args.investing_slug).items():
            print(f"Capturing {name}: {url}", flush=True)
            response = client.post(
                f"{args.base_url}/api/browser-tasks/test-extract",
                json={
                    "url": url,
                    "timeout_seconds": args.timeout,
                    "ticker": ticker,
                    "include_full_text": True,
                },
            )
            response.raise_for_status()
            payload = response.json()
            payload["captured_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            output_path = output_dir / f"{name}.json"
            output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            print(
                json.dumps(
                    {
                        "name": name,
                        "status": payload.get("status"),
                        "chars": payload.get("text_char_count"),
                        "path": str(output_path),
                    }
                ),
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
