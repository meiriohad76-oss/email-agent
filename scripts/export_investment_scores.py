from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from email_article_analyzer.config import AppConfig  # noqa: E402
from email_article_analyzer.investment_scoring import score_company_research  # noqa: E402
from email_article_analyzer.repositories import RunRepository  # noqa: E402
from email_article_analyzer.sector_scoring import apply_sector_models  # noqa: E402


def load_sector_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            str(row.get("Ticker") or "").strip().upper(): str(row.get("Sector") or "Unclassified").strip()
            for row in csv.DictReader(handle)
            if row.get("Ticker")
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export coverage-aware investment factor scores.")
    parser.add_argument("run_id", type=int)
    parser.add_argument("--ticker", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "investment_scores")
    args = parser.parse_args()

    requested = {ticker.strip().upper() for ticker in args.ticker if ticker.strip()}
    enrichments = RunRepository(AppConfig.from_env().database_path).list_ticker_enrichments(args.run_id)
    grouped: dict[str, list[dict]] = {}
    for enrichment in enrichments:
        ticker = str(enrichment["ticker"]).upper()
        if requested and ticker not in requested:
            continue
        if enrichment["status"] != "ready" or enrichment["provider"] == "polygon":
            continue
        grouped.setdefault(ticker, []).append(dict(enrichment.get("data") or {}))

    results = [score_company_research(records) for _, records in sorted(grouped.items())]
    sector_map = load_sector_map(ROOT / "data" / "research_universe_120.csv")
    sector_companies = [
        {
            "ticker": result["ticker"],
            "sector": sector_map.get(result["ticker"], "Unclassified"),
            "categories": {name: category["score"] for name, category in result["categories"].items()},
        }
        for result in results
    ]
    apply_sector_models(sector_companies)
    sector_results = {company["ticker"]: company for company in sector_companies}
    sector_fields = (
        "sector", "sector_model_version", "sector_model_score", "sector_model_coverage",
        "sector_model_rank", "sector_model_percentile", "sector_model_cohort_size",
        "sector_model_rank_eligible", "sector_model_limitation",
    )
    for result in results:
        model = sector_results[result["ticker"]]
        result.update({name: model.get(name) for name in sector_fields})
    results.sort(
        key=lambda item: (
            not item["comparable_rank_eligible"],
            -(item["composite_score"] if item["composite_score"] is not None else -1),
        )
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"run_{args.run_id}_investment_scores"
    json_path = args.output_dir / f"{stem}.json"
    summary_path = args.output_dir / f"{stem}_summary.csv"
    evidence_path = args.output_dir / f"{stem}_evidence.csv"
    sources_path = args.output_dir / f"{stem}_sources.csv"
    sources_json_path = args.output_dir / f"{stem}_sources.json"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    category_names = list(results[0]["categories"]) if results else []
    with summary_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "rank", "ticker", "sector", "sector_model_rank", "sector_model_score",
                "sector_model_coverage", "sector_model_percentile", "sector_model_cohort_size",
                "sector_model_version", "composite_score", "score_coverage", "comparable_rank_eligible",
                *[f"{name}_score" for name in category_names],
                *[f"{name}_signal_count" for name in category_names],
            ],
        )
        writer.writeheader()
        eligible_rank = 0
        for result in results:
            if result["comparable_rank_eligible"]:
                eligible_rank += 1
                rank = eligible_rank
            else:
                rank = ""
            row = {
                "rank": rank,
                "ticker": result["ticker"],
                "sector": result["sector"],
                "sector_model_rank": result["sector_model_rank"],
                "sector_model_score": result["sector_model_score"],
                "sector_model_coverage": result["sector_model_coverage"],
                "sector_model_percentile": result["sector_model_percentile"],
                "sector_model_cohort_size": result["sector_model_cohort_size"],
                "sector_model_version": result["sector_model_version"],
                "composite_score": result["composite_score"],
                "score_coverage": result["score_coverage"],
                "comparable_rank_eligible": result["comparable_rank_eligible"],
            }
            for name, category in result["categories"].items():
                row[f"{name}_score"] = category["score"]
                row[f"{name}_signal_count"] = category["signal_count"]
            writer.writerow(row)

    with evidence_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "ticker", "category", "category_score", "evidence_label", "evidence_score",
                "evidence_weight", "raw_value",
            ],
        )
        writer.writeheader()
        for result in results:
            for category_name, category in result["categories"].items():
                for evidence in category["evidence"]:
                    writer.writerow(
                        {
                            "ticker": result["ticker"],
                            "category": category_name,
                            "category_score": category["score"],
                            "evidence_label": evidence["label"],
                            "evidence_score": evidence["score"],
                            "evidence_weight": evidence["weight"],
                            "raw_value": json.dumps(evidence["raw"], ensure_ascii=True),
                        }
                    )
    source_rows = []
    with sources_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["ticker", "provider", "data_type", "status", "source_url", "failure_reason"],
        )
        writer.writeheader()
        for enrichment in enrichments:
            ticker = str(enrichment["ticker"]).upper()
            if requested and ticker not in requested:
                continue
            row = {
                "ticker": ticker,
                "provider": enrichment["provider"],
                "data_type": enrichment["data_type"],
                "status": enrichment["status"],
                "source_url": enrichment.get("source_url") or "",
                "failure_reason": enrichment.get("failure_reason") or "",
            }
            source_rows.append(row)
            writer.writerow(row)
    sources_json_path.write_text(json.dumps(source_rows, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "companies": len(results), "json": str(json_path), "summary": str(summary_path),
                "evidence": str(evidence_path), "sources": str(sources_path),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
