from __future__ import annotations

import argparse
from pathlib import Path

from email_article_analyzer.report_pdf_export import build_run_html_report, build_run_pdf_report
from email_article_analyzer.repositories import RunRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the modern PDF report for a discovery run.")
    parser.add_argument("run_id", type=int)
    parser.add_argument("--database", default="data/app.db")
    parser.add_argument("--output-dir", default="output/pdf")
    args = parser.parse_args()

    repository = RunRepository(args.database)
    run = repository.get_run(args.run_id)
    counts = repository.discovery_counts(args.run_id)
    events = repository.list_events(args.run_id)
    articles = repository.list_discovered_articles(args.run_id)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"run-{args.run_id}-stock-article-intelligence-modern"
    html_path = output_dir / f"{stem}.html"
    pdf_path = output_dir / f"{stem}.pdf"

    html = build_run_html_report(run, counts, events, articles)
    html_path.write_text(html, encoding="utf-8")
    pdf_path.write_bytes(build_run_pdf_report(run, counts, events, articles))

    print(pdf_path)


if __name__ == "__main__":
    main()
