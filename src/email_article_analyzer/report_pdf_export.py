from __future__ import annotations

from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Callable


PdfRenderer = Callable[[str], bytes]


def build_run_pdf_report(
    run: dict[str, Any],
    counts: dict[str, int],
    events: list[dict[str, Any]],
    articles: list[dict[str, Any]],
    pdf_renderer: PdfRenderer | None = None,
) -> bytes:
    renderer = pdf_renderer or render_html_to_pdf
    return renderer(build_run_html_report(run, counts, events, articles))


def build_run_html_report(
    run: dict[str, Any],
    counts: dict[str, int],
    events: list[dict[str, Any]],
    articles: list[dict[str, Any]],
) -> str:
    metrics = _metrics(counts, events, articles)
    linked = sorted(
        [article for article in articles if _portfolio_tickers(article)],
        key=_priority_score,
        reverse=True,
    )
    targets = _price_targets(articles)
    appendix = [article for article in articles if article.get("analysis")]

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Daily Stock Article Intelligence - Run #{_e(run.get("id"))}</title>
<style>
  @page {{ size: letter; margin: 0.58in 0.62in; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; color: #1B2233; font-family: Arial, Helvetica, sans-serif; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  .doc {{ max-width: 8.5in; margin: 0 auto; }}
  .brand {{ display:flex; align-items:center; gap:11px; margin-bottom:18px; }}
  .logo {{ width:34px; height:34px; border-radius:9px; background:#2D4EF5; color:#fff; display:flex; align-items:center; justify-content:center; font-weight:800; }}
  .eyebrow {{ font-size:10px; letter-spacing:.14em; text-transform:uppercase; color:#8A93A6; font-weight:700; }}
  h1 {{ font-size:31px; font-weight:800; letter-spacing:-.02em; line-height:1.12; margin:0 0 12px; }}
  h2 {{ font-size:15px; font-weight:800; margin:28px 0 7px; color:#1B2233; }}
  h3 {{ font-size:13px; font-weight:800; margin:16px 0 6px; color:#1B2233; }}
  p {{ font-size:12px; line-height:1.55; color:#3A4358; margin:0 0 10px; }}
  .meta {{ display:flex; flex-wrap:wrap; gap:8px 12px; align-items:center; font-family: Consolas, monospace; font-size:10.5px; color:#6B7488; margin-bottom:24px; }}
  .pill {{ display:inline-flex; align-items:center; gap:6px; font-weight:700; color:#0B7A50; background:#E4F6ED; border:1px solid #BBE7D1; padding:2px 9px; border-radius:999px; font-family:Arial,sans-serif; font-size:10px; }}
  .dot {{ width:6px; height:6px; border-radius:50%; background:#12A06B; }}
  .statband {{ display:grid; grid-template-columns:repeat(6,1fr); gap:1px; background:#E4E8F0; border:1px solid #E4E8F0; border-radius:12px; overflow:hidden; margin:20px 0 12px; break-inside:avoid; }}
  .stat {{ background:#fff; padding:13px 12px; }}
  .stat-value {{ font-family:Consolas,monospace; font-size:20px; font-weight:700; letter-spacing:-.02em; }}
  .stat-label {{ font-size:10.5px; color:#6B7488; margin-top:3px; }}
  .mixbar {{ display:flex; height:14px; border-radius:7px; overflow:hidden; gap:2px; margin:8px 0 7px; }}
  .legend {{ display:flex; flex-wrap:wrap; gap:6px 18px; font-size:10.5px; color:#6B7488; margin-bottom:26px; }}
  .swatch {{ display:inline-block; width:8px; height:8px; border-radius:2px; margin-right:6px; }}
  table {{ width:100%; border-collapse:collapse; margin:10px 0 18px; }}
  th {{ text-align:left; font-size:9.5px; font-weight:800; text-transform:uppercase; letter-spacing:.06em; color:#8A93A6; padding:8px 9px; border-bottom:1.5px solid #E4E8F0; }}
  td {{ font-size:11px; line-height:1.42; color:#36405A; padding:9px; border-bottom:1px solid #EEF1F6; vertical-align:top; }}
  tr {{ break-inside:avoid; }}
  .mono {{ font-family:Consolas,monospace; }}
  .badge {{ font-size:10px; font-weight:800; padding:2px 8px; border-radius:999px; white-space:nowrap; }}
  .buy {{ background:#E4F6ED; color:#0B7A50; border:1px solid #BBE7D1; }}
  .sell {{ background:#FCEBE9; color:#C0352A; border:1px solid #F4C9C4; }}
  .hold {{ background:#EEF1F6; color:#46546E; border:1px solid #DEE4EE; }}
  .unclear {{ background:#FBF1DD; color:#A9701A; border:1px solid #F0DCB2; }}
  .two-up {{ display:grid; grid-template-columns:1fr 1fr; gap:24px; margin:14px 0 26px; break-inside:avoid; }}
  .metric-row {{ display:flex; justify-content:space-between; gap:12px; padding:9px 0; border-bottom:1px solid #EEF1F6; }}
  .metric-name {{ font-size:12px; font-weight:700; color:#1B2233; }}
  .metric-note {{ font-size:10.5px; color:#9AA3B4; margin-top:1px; }}
  .metric-value {{ font-family:Consolas,monospace; font-size:12.5px; font-weight:700; color:#0B7A50; white-space:nowrap; }}
  .step {{ display:flex; gap:10px; align-items:flex-start; margin-bottom:10px; }}
  .step-num {{ flex-shrink:0; width:19px; height:19px; border-radius:6px; background:#EAEEFF; color:#2D4EF5; font-family:Consolas,monospace; font-size:11px; font-weight:700; display:flex; align-items:center; justify-content:center; }}
  .appendix-title {{ font-size:17px; font-weight:800; margin:28px 0 6px; padding-top:8px; border-top:2px solid #1B2233; }}
  .card {{ border:1px solid #E6EAF1; border-radius:12px; padding:14px 16px; margin-bottom:12px; break-inside:avoid; }}
  .card.buy-border {{ border-left:3px solid #12A06B; }}
  .card.sell-border {{ border-left:3px solid #E24A3B; }}
  .card.hold-border {{ border-left:3px solid #64748B; }}
  .card.unclear-border {{ border-left:3px solid #E0A53B; }}
  .card-head {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; margin-bottom:7px; }}
  .card-title {{ font-size:13.5px; font-weight:800; line-height:1.3; }}
  .ticker {{ font-family:Consolas,monospace; font-size:9.5px; font-weight:600; padding:1px 6px; border-radius:5px; display:inline-block; margin:0 4px 4px 0; }}
  .ticker.portfolio {{ background:#EAEEFF; color:#2440D9; border:1px solid #CBD5FF; }}
  .ticker.other {{ background:#F1F3F8; color:#6B7891; border:1px solid #E4E8F0; }}
  .label {{ font-size:9.5px; font-weight:800; text-transform:uppercase; letter-spacing:.06em; color:#9AA3B4; margin:8px 0 5px; }}
  .mini {{ font-size:10.5px; line-height:1.45; color:#4A5468; margin-bottom:4px; }}
  .callout {{ background:#FBF1DD; border:1px solid #F0DCB2; border-radius:10px; padding:12px 15px; margin-top:18px; break-inside:avoid; }}
  .muted {{ color:#6B7488; }}
</style>
</head>
<body>
<main class="doc">
  <div class="brand"><div class="logo">▥</div><div class="eyebrow">Email Article Analyzer - automated research briefing</div></div>
  <h1>Daily Stock Article Intelligence</h1>
  <div class="meta"><span class="pill"><span class="dot"></span>{_e(str(run.get("status", "")).upper())}</span><span>Run #{_e(run.get("id"))}</span><span>-</span><span>{_e(_date(run.get("started_at")))} -> {_e(_time(run.get("completed_at")))}</span><span>-</span><span>Extraction {_e(run.get("extraction_model"))} / Summary {_e(run.get("summary_model"))}</span></div>

  <h2>Executive summary</h2>
  {_executive_summary(metrics)}

  {_statband(metrics)}
  {_action_mix(metrics)}

  <h2>Portfolio-linked articles - first review pass</h2>
  <p>{metrics["portfolio_count"]} articles mention a current watchlist ticker. Higher-confidence buy- and sell-watch items are prioritized, since those create the most immediate review burden.</p>
  {_priority_table(linked[:14])}

  <h2>Price targets need market context before acting</h2>
  <p>Targets, deal prices, and reference levels are shown where articles gave them. Next step: join to live price, daily move, and volatility before interpreting upside/downside.</p>
  {_target_table(targets[:9])}
  <p class="muted"><em>Showing the first {min(len(targets), 9)} extracted valuation rows out of {len(targets)} total rows; detailed article notes remain in the appendix.</em></p>

  <div class="two-up">
    <section><h2>Extraction quality</h2>{_quality_rows(metrics)}</section>
    <section><h2>Recommended next steps</h2>{_next_steps(metrics)}</section>
  </div>

  <div class="appendix-title">Detailed article appendix</div>
  <p>All {len(appendix)} analyzed articles, with model summary, supporting evidence, catalysts, and risks.</p>
  {_appendix_cards(appendix)}

  <div class="callout"><span class="label">Caveat </span><span class="mini">This report summarizes third-party article analysis and automated LLM extraction. It is not investment advice and should not be used as the sole basis for trading decisions.</span></div>
</main>
</body>
</html>"""


def render_html_to_pdf(html: str, chrome_path: str | None = None) -> bytes:
    chrome = chrome_path or _find_chrome()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        html_path = temp_path / "report.html"
        pdf_path = temp_path / "report.pdf"
        profile_path = temp_path / "chrome-profile"
        html_path.write_text(html, encoding="utf-8")
        subprocess.run(
            [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                f"--user-data-dir={profile_path}",
                "--no-pdf-header-footer",
                f"--print-to-pdf={pdf_path}",
                html_path.as_uri(),
            ],
            check=True,
            capture_output=True,
        )
        return pdf_path.read_bytes()


def _find_chrome() -> str:
    candidates = [
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("Chrome or Edge was not found for PDF export")


def _metrics(counts: dict[str, int], events: list[dict[str, Any]], articles: list[dict[str, Any]]) -> dict[str, Any]:
    analyzed = [article for article in articles if article.get("analysis")]
    stance_counts = Counter(_signal(article) for article in analyzed)
    fetched = sum(1 for article in articles if (article.get("content") or {}).get("fetch_status") == "fetched")
    text_counts = [(article.get("content") or {}).get("text_char_count") or 0 for article in articles]
    return {
        "article_count": counts.get("article_links", len(articles)),
        "portfolio_count": sum(1 for article in analyzed if _portfolio_tickers(article)),
        "buy_watch": stance_counts["Buy Watch"],
        "sell_watch": stance_counts["Sell Watch"],
        "hold": stance_counts["Hold"],
        "unclear": stance_counts["Unclear"],
        "warnings": sum(1 for event in events if event.get("severity") != "info"),
        "full_fetch_rate": _percent(fetched / len(articles) if articles else 0),
        "fallbacks": sum(1 for article in articles if (article.get("content") or {}).get("fetch_status") == "email_fallback"),
        "low_confidence": sum(1 for article in analyzed if ((article.get("analysis") or {}).get("confidence") or 0) < 0.7),
        "avg_chars": int(sum(text_counts) / len(text_counts)) if text_counts else 0,
    }


def _executive_summary(metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"<p><b>The run completed successfully and produced a high-quality data set.</b> It analyzed {metrics['article_count']} article links with {metrics['full_fetch_rate']} full-content fetch coverage and {metrics['fallbacks']} email-body fallbacks.</p>",
            f"<p><b>Portfolio relevance is high.</b> {metrics['portfolio_count']} of {metrics['article_count']} articles mentioned at least one ticker currently present in the uploaded watchlist or portfolio.</p>",
            f"<p><b>The action mix is balanced but not quiet.</b> The model classified {metrics['buy_watch']} buy-watch articles, {metrics['sell_watch']} sell-watch articles, {metrics['hold']} holds, and {metrics['unclear']} unclear items.</p>",
        ]
    )


def _statband(metrics: dict[str, Any]) -> str:
    cards = [
        (metrics["article_count"], "Articles", ""),
        (metrics["full_fetch_rate"], "Full fetch", "color:#0B7A50"),
        (metrics["portfolio_count"], "Portfolio", ""),
        (metrics["buy_watch"], "Buy-watch", "color:#12A06B"),
        (metrics["sell_watch"], "Sell-watch", "color:#E24A3B"),
        (metrics["warnings"], "Warnings", ""),
    ]
    items = "".join(
        f'<div class="stat"><div class="stat-value" style="{style}">{_e(value)}</div><div class="stat-label">{_e(label)}</div></div>'
        for value, label, style in cards
    )
    return f'<div class="statband">{items}</div>'


def _action_mix(metrics: dict[str, Any]) -> str:
    total = max(1, metrics["buy_watch"] + metrics["sell_watch"] + metrics["hold"] + metrics["unclear"])
    segments = [
        ("#12A06B", metrics["buy_watch"], "Buy-watch"),
        ("#E24A3B", metrics["sell_watch"], "Sell-watch"),
        ("#64748B", metrics["hold"], "Holds"),
        ("#E0A53B", metrics["unclear"], "Unclear"),
    ]
    bars = "".join(f'<div style="width:{count / total * 100:.2f}%;background:{color}"></div>' for color, count, _ in segments if count)
    legend = "".join(
        f'<span><span class="swatch" style="background:{color}"></span>{count} {label}</span>'
        for color, count, label in segments
    )
    return f'<div class="mixbar">{bars}</div><div class="legend">{legend}<span style="margin-left:auto" class="mono">Avg {metrics["avg_chars"]:,} chars/article</span></div>'


def _priority_table(articles: list[dict[str, Any]]) -> str:
    rows = "".join(
        f"<tr><td class='mono'>{_e(_ticker_summary(_portfolio_tickers(article)))}</td><td><b>{_e(_title(article))}</b></td><td>{_badge(_signal(article))}</td><td class='mono'>{_percent((_analysis(article).get('confidence') or 0))}</td><td>{_e(_action_label(article))}</td></tr>"
        for article in articles
    )
    return f"<table><thead><tr><th>Ticker(s)</th><th>Article</th><th>Signal</th><th>Conf.</th><th>Action</th></tr></thead><tbody>{rows}</tbody></table>"


def _target_table(targets: list[dict[str, Any]]) -> str:
    rows = "".join(
        f"<tr><td class='mono'><b>{_e(row['ticker'])}</b></td><td>{_e(row['reference'])}</td><td class='mono'>{_e(row['value'])}</td><td>{_e(row['timeframe'])}</td></tr>"
        for row in targets
    )
    return f"<table><thead><tr><th>Ticker</th><th>Reference</th><th>Value</th><th>Timeframe</th></tr></thead><tbody>{rows}</tbody></table>"


def _quality_rows(metrics: dict[str, Any]) -> str:
    rows = [
        ("Full article fetch", metrics["full_fetch_rate"], "Strong enough for article-level analysis."),
        ("Email fallbacks", metrics["fallbacks"], "No fallback analysis is ideal."),
        ("Warnings", metrics["warnings"], "Source-login or extraction regressions appear here."),
        ("Low confidence analysis", metrics["low_confidence"], "Review these before acting."),
        ("Average text length", f"{metrics['avg_chars']:,} chars", "Full-page extraction health signal."),
    ]
    return "".join(
        f'<div class="metric-row"><div><div class="metric-name">{_e(name)}</div><div class="metric-note">{_e(note)}</div></div><div class="metric-value">{_e(value)}</div></div>'
        for name, value, note in rows
    )


def _next_steps(metrics: dict[str, Any]) -> str:
    steps = [
        "Review portfolio-linked sell-watch articles before looking at new buy ideas.",
        "Add Polygon market context to price-target rows: current price, 1-day move, 20-day volatility, and upside/downside.",
        "Add dashboard filters for portfolio-only, buy-watch, sell-watch, and low-confidence articles.",
        "Keep run-quality checks in every PDF so source-login or extraction regressions are visible immediately.",
    ]
    return "".join(f'<div class="step"><span class="step-num">{index}</span><span>{_e(text)}</span></div>' for index, text in enumerate(steps, 1))


def _appendix_cards(articles: list[dict[str, Any]]) -> str:
    return "".join(_appendix_card(index, article) for index, article in enumerate(articles, 1))


def _appendix_card(index: int, article: dict[str, Any]) -> str:
    analysis = _analysis(article)
    signal = _signal(article)
    border = _signal_class(signal)
    tickers = "".join(
        f'<span class="ticker {"portfolio" if ticker.get("in_portfolio") else "other"}">{_e(ticker.get("ticker"))}</span>'
        for ticker in analysis.get("mentioned_ticker_details") or []
    )
    evidence = "".join(f'<div class="mini">| {_e(item)}</div>' for item in (analysis.get("supporting_evidence") or [])[:3])
    action = (analysis.get("actionable_data") or [{}])[0]
    catalysts = "".join(f'<div class="mini">- {_e(item)}</div>' for item in (action.get("catalysts") or [])[:3])
    risks = "".join(f'<div class="mini">- {_e(item)}</div>' for item in (action.get("risks") or [])[:3])
    content = article.get("content") or {}
    return f"""
    <article class="card {border}-border">
      <div class="card-head"><div><span class="mono muted">{index:02d}</span> <span class="card-title">{_e(_title(article))}</span></div><div>{_e(_percent(analysis.get("confidence") or 0))} {_badge(signal)}</div></div>
      <div>{tickers}<span class="mono muted">{_e(article.get("source_key"))} - {_e(content.get("text_char_count") or 0)} chars</span></div>
      <p><b>Summary:</b> {_e(analysis.get("summary"))}</p>
      <div class="label">Evidence</div>{evidence}
      <div class="two-up"><div><div class="label">Catalysts</div>{catalysts or '<div class="mini">-</div>'}</div><div><div class="label">Risks</div>{risks or '<div class="mini">-</div>'}</div></div>
    </article>"""


def _price_targets(articles: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows = []
    for article in articles:
        for target in _analysis(article).get("price_targets") or []:
            price = target.get("target_price")
            rows.append(
                {
                    "ticker": _clean(target.get("ticker") or "-"),
                    "reference": _clean(target.get("source_text") or _title(article)),
                    "value": "-" if price is None else f"{_clean(target.get('currency') or 'USD')} {price:g}",
                    "timeframe": _clean(target.get("timeframe") or "-"),
                }
            )
    return rows


def _analysis(article: dict[str, Any]) -> dict[str, Any]:
    return article.get("analysis") or {}


def _title(article: dict[str, Any]) -> str:
    return _clean((article.get("content") or {}).get("title") or article.get("subject") or "Untitled article")


def _portfolio_tickers(article: dict[str, Any]) -> list[str]:
    return [
        _clean(ticker.get("ticker")).upper()
        for ticker in _analysis(article).get("mentioned_ticker_details") or []
        if ticker.get("in_portfolio")
    ]


def _ticker_summary(tickers: list[str], limit: int = 5) -> str:
    if len(tickers) <= limit:
        return ", ".join(tickers)
    return ", ".join(tickers[:limit] + [f"+{len(tickers) - limit}"])


def _signal(article: dict[str, Any]) -> str:
    stance = str(_analysis(article).get("stance") or "unclear").lower()
    if stance == "buy_watch":
        return "Buy Watch"
    if stance == "sell_watch":
        return "Sell Watch"
    if stance == "hold":
        return "Hold"
    return "Unclear"


def _signal_class(signal: str) -> str:
    return {"Buy Watch": "buy", "Sell Watch": "sell", "Hold": "hold"}.get(signal, "unclear")


def _badge(signal: str) -> str:
    return f'<span class="badge {_signal_class(signal)}">{_e(signal)}</span>'


def _priority_score(article: dict[str, Any]) -> float:
    signal = _signal(article)
    signal_weight = {"Sell Watch": 4, "Buy Watch": 3, "Unclear": 2, "Hold": 1}.get(signal, 0)
    return signal_weight + float(_analysis(article).get("confidence") or 0)


def _action_label(article: dict[str, Any]) -> str:
    signal = _signal(article)
    if signal == "Sell Watch":
        return "Risk review"
    if signal == "Buy Watch":
        return "Research"
    return "Monitor"


def _percent(value: float) -> str:
    return f"{float(value) * 100:.0f}%"


def _date(value: Any) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(str(value)).strftime("%b %d, %Y %H:%M")
    except ValueError:
        return _clean(value)


def _time(value: Any) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(str(value)).strftime("%H:%M")
    except ValueError:
        return _clean(value)


def _e(value: Any) -> str:
    return escape(_clean(value))


def _clean(value: Any) -> str:
    if value is None:
        return ""
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
    }
    text = str(value)
    for source, target in replacements.items():
        text = text.replace(source, target)
    return " ".join(text.split())
