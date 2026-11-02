from __future__ import annotations

from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Callable

from email_article_analyzer.watchlist import normalize_ticker


PdfRenderer = Callable[[str], bytes]


def build_run_pdf_report(
    run: dict[str, Any],
    counts: dict[str, int],
    events: list[dict[str, Any]],
    articles: list[dict[str, Any]],
    market_data_by_ticker: dict[str, dict[str, Any]] | None = None,
    rating_data_by_ticker: dict[str, list[dict[str, Any]]] | None = None,
    pdf_renderer: PdfRenderer | None = None,
) -> bytes:
    renderer = pdf_renderer or render_html_to_pdf
    return renderer(
        build_run_html_report(
            run,
            counts,
            events,
            articles,
            market_data_by_ticker,
            rating_data_by_ticker,
        )
    )


def build_run_html_report(
    run: dict[str, Any],
    counts: dict[str, int],
    events: list[dict[str, Any]],
    articles: list[dict[str, Any]],
    market_data_by_ticker: dict[str, dict[str, Any]] | None = None,
    rating_data_by_ticker: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    metrics = _metrics(counts, events, articles)
    usable_articles = [article for article in articles if _is_usable_article(article)]
    action_cards = _ticker_action_cards(
        usable_articles,
        market_data_by_ticker or {},
        rating_data_by_ticker or {},
    )
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
  .bluf {{ border:1px solid #D8E6F8; border-radius:12px; background:#F7FAFF; padding:14px 16px; margin:18px 0 18px; break-inside:avoid; }}
  .bluf h2 {{ margin-top:0; }}
  .bluf-list {{ display:grid; gap:8px; margin-top:9px; }}
  .bluf-item {{ display:grid; grid-template-columns:84px 122px 1fr; gap:10px; align-items:start; border-top:1px solid #E2EAF7; padding-top:8px; }}
  .bluf-item:first-child {{ border-top:0; padding-top:0; }}
  .bluf-rank {{ font-family:Consolas,monospace; font-size:10px; font-weight:800; color:#6B7488; }}
  .bluf-ticker {{ font-family:Consolas,monospace; font-size:13px; font-weight:800; color:#1B2233; }}
  .bluf-action {{ font-size:10px; font-weight:800; text-transform:uppercase; letter-spacing:.04em; color:#2440D9; }}
  .bluf-reason {{ font-size:11px; line-height:1.42; color:#36405A; }}
  .action-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin:10px 0 20px; }}
  .ticker-review-list {{ display:grid; gap:14px; margin:10px 0 20px; }}
  .action-card {{ border:1px solid #E6EAF1; border-radius:12px; padding:14px 16px; break-inside:auto; }}
  .action-title {{ font-size:16px; font-weight:800; margin-bottom:3px; }}
  .action-subtitle {{ font-size:10.5px; color:#6B7488; margin-bottom:8px; }}
  .action-line {{ display:flex; justify-content:space-between; gap:10px; border-top:1px solid #EEF1F6; padding:6px 0; font-size:10.5px; }}
  .action-line b {{ color:#1B2233; }}
  .action-value {{ text-align:right; color:#36405A; }}
  .ticker-section-head {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; border-bottom:1px solid #E6EAF1; padding-bottom:8px; margin-bottom:9px; }}
  .ticker-headline {{ font-size:11px; color:#36405A; line-height:1.45; }}
  .ticker-facts {{ display:grid; grid-template-columns:1fr 1fr; gap:0 18px; margin:6px 0 10px; }}
  .ticker-narrative {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin:10px 0; }}
  .note-list {{ margin:0; padding-left:16px; }}
  .note-list li {{ font-size:10.5px; color:#4A5468; line-height:1.45; margin:2px 0; }}
  .article-note {{ border-top:1px solid #EEF1F6; padding-top:10px; margin-top:10px; break-inside:avoid; }}
  .article-note-title {{ font-size:11px; font-weight:800; color:#1B2233; }}
  .article-note-meta {{ font-size:9.8px; color:#6B7488; margin:2px 0 4px; }}
  .article-note a {{ color:#2D4EF5; overflow-wrap:anywhere; }}
  .article-note-summary {{ font-size:10.7px; line-height:1.55; color:#3E485D; margin:5px 0 0; }}
  .article-note-summary b {{ color:#1B2233; }}
</style>
</head>
<body>
<main class="doc">
  <div class="brand"><div class="logo">▥</div><div class="eyebrow">Email Article Analyzer - automated research briefing</div></div>
  <h1>Daily Stock Article Intelligence</h1>
  <div class="meta"><span class="pill"><span class="dot"></span>{_e(str(run.get("status", "")).upper())}</span><span>Run #{_e(run.get("id"))}</span><span>-</span><span>{_e(_date(run.get("started_at")))} -> {_e(_time(run.get("completed_at")))}</span><span>-</span><span>Article analysis model {_e(run.get("summary_model"))}</span></div>

  {_bluf_section(action_cards)}

  <h2>Executive summary</h2>
  {_executive_summary(metrics)}

  {_statband(metrics)}
  {_action_mix(metrics)}

  <h2>Unified ticker review</h2>
  <p>{len(action_cards)} tickers are consolidated below. Every ticker appears in one section only; article-derived recommendations, evidence, enrichments, price targets, Polygon context, and source links are kept inside that ticker summary.</p>
  {_action_card_grid(action_cards)}

  <div class="two-up">
    <section><h2>Extraction quality</h2>{_quality_rows(metrics)}</section>
    <section><h2>Recommended next steps</h2>{_next_steps(metrics)}</section>
  </div>

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
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("Chrome or Edge was not found for PDF export")


def _metrics(counts: dict[str, int], events: list[dict[str, Any]], articles: list[dict[str, Any]]) -> dict[str, Any]:
    analyzed = [article for article in articles if article.get("analysis")]
    usable_analyzed = [article for article in analyzed if not _has_pdf_quality_issue(article)]
    stance_counts = Counter(_signal(article) for article in usable_analyzed)
    blocked = sum(1 for article in articles if _is_blocked_article(article))
    low_quality = sum(1 for article in articles if _has_pdf_quality_issue(article))
    usable = sum(1 for article in articles if _is_usable_article(article))
    fetched = sum(
        1
        for article in articles
        if _is_usable_article(article)
        and (article.get("content") or {}).get("fetch_status") == "fetched"
    )
    text_counts = [(article.get("content") or {}).get("text_char_count") or 0 for article in articles]
    article_count = counts.get("article_links", len(articles))
    return {
        "article_count": article_count,
        "usable_count": usable,
        "blocked_count": blocked,
        "quality_issue_count": low_quality,
        "portfolio_count": sum(
            1
            for article in usable_analyzed
            if _portfolio_tickers(article)
        ),
        "buy_watch": stance_counts["Buy Watch"],
        "sell_watch": stance_counts["Sell Watch"],
        "hold": stance_counts["Hold"],
        "unclear": stance_counts["Unclear"],
        "warnings": sum(1 for event in events if event.get("severity") != "info"),
        "full_fetch_rate": _percent(fetched / usable if usable else 0),
        "fallbacks": sum(1 for article in articles if (article.get("content") or {}).get("fetch_status") == "email_fallback"),
        "low_confidence": sum(1 for article in analyzed if ((article.get("analysis") or {}).get("confidence") or 0) < 0.7),
        "avg_chars": int(sum(text_counts) / len(text_counts)) if text_counts else 0,
    }


def _executive_summary(metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"<p><b>The run produced {metrics['usable_count']} / {metrics['article_count']} usable article records.</b> {metrics['blocked_count']} links were blocked by source verification or access checks and should be retried before investment review.</p>",
            f"<p><b>Portfolio relevance is based on usable content only.</b> {metrics['portfolio_count']} usable articles mentioned at least one ticker currently present in the uploaded watchlist or portfolio.</p>",
            f"<p><b>The action mix should be read after quality filtering.</b> The model classified {metrics['buy_watch']} buy-watch articles, {metrics['sell_watch']} sell-watch articles, {metrics['hold']} holds, and {metrics['unclear']} unclear items.</p>",
        ]
    )


def _statband(metrics: dict[str, Any]) -> str:
    cards = [
        (metrics["article_count"], "Articles", ""),
        (f"{metrics['usable_count']} / {metrics['article_count']}", "Usable articles", "color:#0B7A50"),
        (metrics["portfolio_count"], "Portfolio", ""),
        (metrics["buy_watch"], "Buy-watch", "color:#12A06B"),
        (metrics["sell_watch"], "Sell-watch", "color:#E24A3B"),
        (metrics["blocked_count"], "Blocked/source-check", "color:#E24A3B"),
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


def _quality_rows(metrics: dict[str, Any]) -> str:
    rows = [
        ("Usable articles", f"{metrics['usable_count']} / {metrics['article_count']}", "Rows safe enough for article-level analysis."),
        ("Full article fetch", metrics["full_fetch_rate"], "Measured only across usable articles."),
        ("Blocked/source-check", metrics["blocked_count"], "Source login, bot check, or human verification issue."),
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


def _bluf_section(cards: list[dict[str, Any]]) -> str:
    items = _bluf_items(cards)
    if not items:
        return """
  <section class="bluf">
    <h2>BLUF - most actionable recommendations</h2>
    <p>No high-clarity ticker actions were generated. Read the unified ticker sections for lower-confidence observations and missing-data checks.</p>
  </section>"""
    rendered = "".join(
        f"""
      <div class="bluf-item">
        <div class="bluf-rank">#{index}</div>
        <div><div class="bluf-ticker">{_e(item['ticker'])}</div><div class="bluf-action">{_e(item['action'])}</div></div>
        <div class="bluf-reason">{_e(item['reason'])}</div>
      </div>"""
        for index, item in enumerate(items, 1)
    )
    return f"""
  <section class="bluf">
    <h2>BLUF - most actionable recommendations</h2>
    <p>Start here. These are the clearest actions from this run; supporting evidence, ratings, targets, and source links remain in each ticker's unified section below.</p>
    <div class="bluf-list">{rendered}
    </div>
  </section>"""


def _bluf_items(cards: list[dict[str, Any]], limit: int = 6) -> list[dict[str, str]]:
    ranked = sorted(cards, key=_bluf_priority, reverse=True)
    return [
        {
            "ticker": card["ticker"],
            "action": _bluf_action(card),
            "reason": _bluf_reason(card),
        }
        for card in ranked[:limit]
        if _bluf_priority(card) > 0
    ]


def _bluf_priority(card: dict[str, Any]) -> float:
    confidence = max(card.get("confidences") or [0])
    score = confidence
    if _has_cross_source_conflict(card):
        score += 6
    signal = card.get("signal_label")
    if signal == "Sell Watch":
        score += 5
    elif signal == "Buy Watch":
        score += 4
    elif signal == "Hold":
        score += 1
    if _has_numeric_upside(card):
        score += 1.5
    if card.get("article_count", 0) > 1:
        score += 0.5
    return score


def _bluf_action(card: dict[str, Any]) -> str:
    if _has_cross_source_conflict(card):
        return "Resolve conflict"
    signal = card.get("signal_label")
    if signal == "Sell Watch":
        return "Risk review"
    if signal == "Buy Watch":
        return "Research now"
    if signal == "Hold":
        return "Monitor"
    return "Low clarity"


def _bluf_reason(card: dict[str, Any]) -> str:
    parts: list[str] = []
    signal = card.get("signal_label")
    if _has_cross_source_conflict(card):
        parts.append(_cross_source_conflict_reason(card))
    elif signal == "Sell Watch":
        parts.append(f"{card['article_consensus']} article read with {card['confidence_summary']} confidence.")
    elif signal == "Buy Watch":
        parts.append(f"{card['article_consensus']} article read with {card['confidence_summary']} confidence.")
    else:
        parts.append(f"{card['article_consensus']} article read.")
    target = _best_available_target_for_bluf(card)
    if target:
        parts.append(target)
    evidence = _unique_text((card.get("evidence") or []) + (card.get("catalysts") or []) + (card.get("risks") or []))
    if evidence:
        parts.append(_truncate(evidence[0], 120))
    parts.append("See unified ticker section for evidence and source links.")
    return " ".join(parts)


def _best_available_target_for_bluf(card: dict[str, Any]) -> str:
    upside = _clean(card.get("upside_downside"))
    if upside and not upside.startswith("needs"):
        return f"Article target implies {upside}."
    for label in [
        "sa_price_target",
        "zacks_price_target",
        "investing_fair_value",
        "investing_analyst_target",
    ]:
        value = _clean(card.get(label))
        if value and "Polygon " in value and "fetch failed" not in value and "source page not fetched" not in value:
            return f"{label.replace('_', ' ').upper()}: {value}."
    return ""


def _has_numeric_upside(card: dict[str, Any]) -> bool:
    upside = _clean(card.get("upside_downside"))
    return bool(upside and not upside.startswith("needs") and "%" in upside)


def _has_cross_source_conflict(card: dict[str, Any]) -> bool:
    signal = card.get("signal_label")
    rating_stances = [_rating_stance(rating) for rating in card.get("rating_snapshots") or []]
    rating_stances = [stance for stance in rating_stances if stance]
    if signal == "Buy Watch" and "sell" in rating_stances:
        return True
    if signal == "Sell Watch" and "buy" in rating_stances:
        return True
    return False


def _cross_source_conflict_reason(card: dict[str, Any]) -> str:
    signal = card.get("signal_label")
    bearish = [rating for rating in card.get("rating_snapshots") or [] if _rating_stance(rating) == "sell"]
    bullish = [rating for rating in card.get("rating_snapshots") or [] if _rating_stance(rating) == "buy"]
    if signal == "Buy Watch" and bearish:
        return f"Article read is Buy Watch, but {_rating_brief(bearish[0])} is bearish."
    if signal == "Sell Watch" and bullish:
        return f"Article read is Sell Watch, but {_rating_brief(bullish[0])} is bullish."
    return "Article read and external ratings conflict."


def _rating_stance(rating: dict[str, Any]) -> str:
    if rating.get("status") in {"failed", "not_applicable"}:
        return ""
    text = f"{rating.get('rating') or ''} {rating.get('source_text') or ''}".lower()
    score = rating.get("score")
    if rating.get("provider") == "zacks" and rating.get("rating_type") == "rank":
        try:
            numeric = float(score)
        except (TypeError, ValueError):
            numeric = None
        if numeric is not None:
            if numeric <= 2:
                return "buy"
            if numeric >= 4:
                return "sell"
        if "rank #1" in text or "rank #2" in text or "strong buy" in text:
            return "buy"
        if "rank #4" in text or "rank #5" in text or "sell" in text:
            return "sell"
    try:
        numeric_score = float(score)
    except (TypeError, ValueError):
        numeric_score = None
    if numeric_score is not None:
        if numeric_score >= 4:
            return "buy"
        if numeric_score <= 2:
            return "sell"
    if "strong buy" in text or re.search(r"\bbuy\b", text):
        return "buy"
    if "strong sell" in text or re.search(r"\bsell\b", text):
        return "sell"
    return ""


def _rating_brief(rating: dict[str, Any]) -> str:
    provider = str(rating.get("provider") or "source").replace("_", " ").title()
    rating_type = str(rating.get("rating_type") or "rating").replace("_", " ")
    value = _clean(rating.get("rating"))
    score = _format_score(rating.get("score"))
    rendered = f"{provider} {rating_type}"
    if value:
        rendered += f" {value}"
    if score is not None:
        rendered += f" ({score})"
    return rendered


def _priority_label(value: Any) -> str:
    # The uploaded "priority" column holds portfolio weights (e.g. 0.0123 for 1.23%),
    # so a fraction between 0 and 1 is shown as a weight instead of a raw number.
    text = _clean(value)
    if not text:
        return "not set"
    try:
        number = float(text)
    except ValueError:
        return f"priority {text}"
    if 0 < number <= 1:
        return f"portfolio weight {number * 100:.2f}%"
    return f"priority {text}"


def _word_stance(text: str) -> str | None:
    lowered = _clean(text).lower()
    if re.search(r"\b(strong buy|buy|outperform)\b", lowered):
        return "buy"
    if re.search(r"\b(hold|neutral)\b", lowered):
        return "hold"
    if re.search(r"\b(strong sell|sell|underperform)\b", lowered):
        return "sell"
    return None


def _source_stance(
    ratings: list[dict[str, Any]],
    provider: str,
    rating_types: tuple[str, ...],
) -> str:
    # Each source is judged by its own rating only; the article stance is never used here.
    for rating_type in rating_types:
        for rating in ratings:
            if rating.get("provider") != provider or rating.get("rating_type") != rating_type:
                continue
            stance = _word_stance(_clean(rating.get("rating"))) or _rating_stance(rating)
            if stance:
                return stance
    return "no rating"


def _source_blocks(card: dict[str, Any]) -> list[dict[str, Any]]:
    ratings = card["rating_snapshots"]
    return [
        {
            "label": "Seeking Alpha",
            "stance": _source_stance(ratings, "seeking_alpha", ("quant", "analysts", "wall_street")),
            "lines": [
                ("Quant rating", card["sa_quant_rating"]),
                ("Analysts rating", card["sa_analysts_rating"]),
                ("Wall Street rating", card["sa_wall_street_rating"]),
                ("Price target", card["sa_price_target"]),
            ],
        },
        {
            "label": "Zacks",
            "stance": _source_stance(ratings, "zacks", ("rank",)),
            "lines": [
                ("Zacks Rank", card["zacks_rank"]),
                ("Price target", card["zacks_price_target"]),
            ],
        },
        {
            "label": "Investing.com (InvestingPro)",
            "stance": _source_stance(ratings, "investing_pro", ("forecast",)),
            "lines": [
                ("Financial health", card["investing_health"]),
                ("Fair value", card["investing_fair_value"]),
                ("Analyst target", card["investing_analyst_target"]),
                ("Ratios", card["investing_ratios"]),
            ],
        },
    ]


def _source_block_html(block: dict[str, Any]) -> str:
    lines = "".join(
        f"<div class='action-line'><b>{_e(label)}:</b><span class='action-value'>{_e(value)}</span></div>"
        for label, value in block["lines"]
        if value
    ) or "<div class='muted'>No data was captured from this source.</div>"
    return f"""
      <div class="source-block" style="border:1px solid #d9dee8;border-radius:8px;padding:8px 10px;margin:6px 0">
        <div><b>{_e(block['label'])}</b> <span class="mono">stance: {_e(block['stance'])}</span></div>
        {lines}
      </div>"""


def _action_card_grid(cards: list[dict[str, Any]]) -> str:
    if not cards:
        return "<p class='muted'>No ticker review sections were generated for this run.</p>"
    return "<div class='ticker-review-list'>" + "".join(_action_card(card) for card in cards) + "</div>"


def _action_card(card: dict[str, Any]) -> str:
    fact_lines = [
        ("Article consensus", card["article_consensus"]),
        ("Confidence", card["confidence_summary"]),
        ("Suggested action", card["suggested_action"]),
        ("Price target", card["price_target_summary"]),
        ("Last close", card["last_close_summary"]),
        ("Upside/downside", card["upside_downside"]),
        ("Polygon reference", card["polygon_reference_summary"]),
        ("Key signals", card["actionable_signal_summary"]),
    ]
    rendered_facts = "".join(
        f"<div class='action-line'><b>{_e(label)}:</b><span class='action-value'>{_e(value)}</span></div>"
        for label, value in fact_lines
    )
    catalysts = _bullet_list(card["catalysts"], "No ticker-specific catalysts extracted.")
    risks = _bullet_list(card["risks"], "No ticker-specific risks extracted.")
    evidence = _bullet_list(card["evidence"], "No ticker-specific evidence extracted.")
    article_notes = _ticker_article_notes(card["articles"])
    source_html = "".join(_source_block_html(block) for block in card["source_blocks"])
    return f"""
    <article class="action-card">
      <div class="ticker-section-head">
        <div>
          <div class="action-title"><span class="mono">{_e(card['ticker'])}</span> {_e(card.get('company_name') or '')}</div>
          <div class="action-subtitle">Asset: {_e(card.get('asset_type') or 'unknown')} - Sector: {_e(card.get('sector') or 'not set')} - {_e(_priority_label(card.get('priority')))} - Articles: {_e(card['article_count'])}</div>
        </div>
        <div>{_badge(card["signal_label"])}</div>
      </div>
      <div class="ticker-headline"><b>Holistic read:</b> {_e(card["article_consensus"])} across {_e(card["article_count"])} article(s). Suggested action: {_e(card["suggested_action"])}. {_e(card["contradiction_summary"])}</div>
      <div class="ticker-facts">{rendered_facts}</div>
      <div class="label">Extraction by source</div>{source_html}
      <div class="ticker-narrative">
        <div><div class="label">Catalysts</div>{catalysts}</div>
        <div><div class="label">Risks</div>{risks}</div>
      </div>
      <div class="label">Evidence</div>{evidence}
      <div class="label">Related articles (stance from each article's own text)</div>{article_notes}
    </article>"""


def _ticker_action_cards(
    articles: list[dict[str, Any]],
    market_data_by_ticker: dict[str, dict[str, Any]],
    rating_data_by_ticker: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    by_ticker: dict[str, dict[str, Any]] = {}
    for article in articles:
        analysis = _analysis(article)
        primary_tickers = _primary_article_tickers(article)
        for detail in analysis.get("mentioned_ticker_details") or []:
            if not detail.get("in_portfolio"):
                continue
            ticker = _clean(detail.get("ticker")).upper()
            if not ticker:
                continue
            ticker_actions = [
                action
                for action in analysis.get("actionable_data") or []
                if normalize_ticker(str(action.get("ticker") or "")) == normalize_ticker(ticker)
            ]
            ticker_signals = [
                signal
                for signal in analysis.get("actionable_signals") or []
                if normalize_ticker(str(signal.get("ticker") or "")) == normalize_ticker(ticker)
            ]
            ticker_targets = [
                target
                for target in analysis.get("price_targets") or []
                if normalize_ticker(str(target.get("ticker") or "")) == normalize_ticker(ticker)
            ]
            ticker_ratings = [
                rating
                for rating in analysis.get("rating_snapshots") or []
                if normalize_ticker(str(rating.get("ticker") or "")) == normalize_ticker(ticker)
            ]
            ticker_has_specific_data = bool(
                ticker_actions or ticker_signals or ticker_targets or ticker_ratings
            )
            # A ticker with source-page ratings keeps every related article, including
            # articles that only mention it, so one section can hold the whole picture.
            has_source_data = bool(rating_data_by_ticker.get(ticker))
            if not ticker_has_specific_data and not has_source_data:
                continue
            if not has_source_data and not _ticker_belongs_in_primary_section(
                ticker,
                primary_tickers,
                ticker_actions,
                ticker_targets,
                ticker_ratings,
            ):
                continue
            card = by_ticker.setdefault(
                ticker,
                {
                    "ticker": ticker,
                    "company_name": detail.get("company_name"),
                    "sector": detail.get("sector"),
                    "priority": detail.get("priority"),
                    "notes": detail.get("notes"),
                    "asset_type": detail.get("asset_type"),
                    "polygon_reference": detail.get("polygon_reference") or {},
                    "sentiments": [],
                    "recommendations": [],
                    "stances": [],
                    "confidences": [],
                    "price_targets": [],
                    "catalysts": [],
                    "risks": [],
                    "evidence": [],
                    "rating_snapshots": [],
                    "actionable_signals": [],
                    "articles": [],
                    "market_data": market_data_by_ticker.get(ticker) or {},
                    "_source_ratings_loaded": False,
                },
            )
            if not card["_source_ratings_loaded"]:
                card["rating_snapshots"].extend(
                    _ratings_with_origin(rating_data_by_ticker.get(ticker) or [], "source_page")
                )
                card["_source_ratings_loaded"] = True
            if ticker_actions:
                card["sentiments"].extend(
                    action.get("sentiment") or analysis.get("sentiment") or "unclear"
                    for action in ticker_actions
                )
                card["recommendations"].extend(
                    action.get("recommendation") or "unclear"
                    for action in ticker_actions
                )
            elif ticker_has_specific_data:
                card["sentiments"].append(analysis.get("sentiment") or "unclear")
                card["recommendations"].append(analysis.get("recommendation") or "unclear")
            else:
                card["sentiments"].append("unclear")
                card["recommendations"].append("unclear")
            card["stances"].append(_ticker_stance(analysis, ticker_actions, ticker_has_specific_data))
            card["confidences"].append(
                _ticker_confidence(analysis, ticker_actions, ticker_has_specific_data)
            )
            card["articles"].append(
                _ticker_article_summary(
                    article,
                    ticker,
                    ticker_actions=ticker_actions,
                    ticker_signals=ticker_signals,
                    ticker_targets=ticker_targets,
                    ticker_ratings=ticker_ratings,
                )
            )
            if ticker_has_specific_data:
                card["evidence"].extend(_ticker_supporting_evidence(analysis, ticker_actions))
            card["price_targets"].extend(ticker_targets)
            card["rating_snapshots"].extend(
                _rating_with_origin(rating, "article")
                for rating in ticker_ratings
            )
            for action in ticker_actions:
                card["catalysts"].extend(action.get("catalysts") or [])
                card["risks"].extend(action.get("risks") or [])
                card["evidence"].extend(action.get("evidence") or [])
            card["actionable_signals"].extend(ticker_signals)
    cards = [_finalize_action_card(card) for card in by_ticker.values()]
    return sorted(cards, key=lambda card: card["ticker"])


def _primary_article_tickers(article: dict[str, Any]) -> set[str]:
    text = " ".join(
        _clean(value)
        for value in [
            _title(article),
            article.get("subject"),
            (article.get("content") or {}).get("title"),
        ]
        if _clean(value)
    )
    tickers: set[str] = set()
    exchange_prefixes = (
        "NYSE",
        "NASDAQ",
        "NYSEARCA",
        "NYSEAMERICAN",
        "AMEX",
        "OTC",
        "OTCMKTS",
    )
    for match in re.finditer(r"\(([A-Z]{1,12}):(?:[A-Z]{2,12})\)", text):
        tickers.add(normalize_ticker(match.group(1)))
    for match in re.finditer(r"\((?:%s):([A-Z][A-Z0-9.-]{0,11})\)" % "|".join(exchange_prefixes), text):
        tickers.add(normalize_ticker(match.group(1)))
    for match in re.finditer(r"\(([A-Z][A-Z0-9.-]{0,11})\)", text):
        candidate = normalize_ticker(match.group(1))
        if candidate not in exchange_prefixes:
            tickers.add(candidate)
    return {ticker for ticker in tickers if ticker}


def _ticker_belongs_in_primary_section(
    ticker: str,
    primary_tickers: set[str],
    ticker_actions: list[dict[str, Any]],
    ticker_targets: list[dict[str, Any]],
    ticker_ratings: list[dict[str, Any]],
) -> bool:
    normalized = normalize_ticker(ticker)
    if not primary_tickers:
        return True
    if normalized in primary_tickers:
        return True
    if ticker_targets or ticker_ratings:
        return True
    return any(_is_direct_secondary_ticker_action(action) for action in ticker_actions)


def _is_direct_secondary_ticker_action(action: dict[str, Any]) -> bool:
    recommendation = str(action.get("recommendation") or "").lower()
    if recommendation in {"", "watch", "unclear"}:
        return False
    text = " ".join(
        _clean(item)
        for item in [
            action.get("source_text"),
            action.get("rationale"),
            action.get("reason"),
            *(action.get("evidence") or []),
            *(action.get("risks") or []),
        ]
        if _clean(item)
    ).lower()
    context_only_markers = [
        "no standalone",
        "no company-specific",
        "mentioned only",
        "used only",
        "used as a peer",
        "peer comparison",
        "competitor",
        "customer",
        "screener rating",
    ]
    return not any(marker in text for marker in context_only_markers)


def _finalize_action_card(card: dict[str, Any]) -> dict[str, Any]:
    best_target = _best_price_target(card["price_targets"])
    reference = card.get("polygon_reference") or {}
    last_close = (card.get("market_data") or {}).get("last_close")
    recommendation = _most_common(card["recommendations"]) or "unclear"
    sentiment = _most_common(card["sentiments"]) or "unclear"
    stance = _most_common(card["stances"]) or "unclear"
    confidence = max(card["confidences"] or [0])
    article_count = len(card["articles"])
    card.update(
        {
            "article_count": article_count,
            "article_consensus": f"{sentiment} / {recommendation}",
            "signal_label": _signal_from_stance(stance),
            "confidence_summary": _confidence_summary(card["confidences"]),
            "suggested_action": _suggested_action(stance, confidence, card),
            "price_target_summary": _price_target_summary(best_target),
            "upside_downside": _upside_downside_summary(best_target, last_close),
            "last_close_summary": _last_close_summary(last_close),
            "polygon_reference_summary": _polygon_reference_summary(reference),
            "sa_quant_rating": _rating_value(card["rating_snapshots"], "seeking_alpha", "quant"),
            "sa_analysts_rating": _rating_value(card["rating_snapshots"], "seeking_alpha", "analysts"),
            "sa_wall_street_rating": _rating_value(
                card["rating_snapshots"],
                "seeking_alpha",
                "wall_street",
                asset_type=card.get("asset_type"),
            ),
            "sa_price_target": _rating_target_value(
                card["rating_snapshots"],
                "seeking_alpha",
                last_close,
                asset_type=card.get("asset_type"),
            ),
            "zacks_rank": _rating_value(
                card["rating_snapshots"],
                "zacks",
                "rank",
                asset_type=card.get("asset_type"),
            ),
            "zacks_price_target": _rating_target_value(
                card["rating_snapshots"],
                "zacks",
                last_close,
                asset_type=card.get("asset_type"),
            ),
            "investing_health": _investing_health_value(card["rating_snapshots"]),
            "investing_fair_value": _investing_fair_value(card["rating_snapshots"], last_close),
            "investing_analyst_target": _investing_analyst_target(card["rating_snapshots"], last_close),
            "investing_ratios": _investing_ratio_summary(card["rating_snapshots"]),
            "actionable_signal_summary": _actionable_signal_summary(card["actionable_signals"]),
            "contradiction_summary": _contradiction_summary(card),
            "priority_score": _card_priority_score(stance, confidence, card),
        }
    )
    card["catalysts"] = _unique_text(card["catalysts"])
    card["risks"] = _unique_text(card["risks"])
    card["evidence"] = _unique_text(card["evidence"])
    card["source_blocks"] = _source_blocks(card)
    return card


def _ticker_stance(
    analysis: dict[str, Any],
    ticker_actions: list[dict[str, Any]],
    ticker_has_specific_data: bool,
) -> str:
    for action in ticker_actions:
        recommendation = str(action.get("recommendation") or "").lower()
        if recommendation in {"buy", "buy_watch"}:
            return "buy_watch"
        if recommendation in {"sell", "sell_watch", "avoid"}:
            return "sell_watch" if recommendation != "avoid" else "avoid"
        if recommendation in {"hold", "neutral"}:
            return "hold"
    return str(analysis.get("stance") or "unclear") if ticker_has_specific_data else "unclear"


def _ticker_confidence(
    analysis: dict[str, Any],
    ticker_actions: list[dict[str, Any]],
    ticker_has_specific_data: bool,
) -> float:
    confidences = [
        float(action.get("confidence"))
        for action in ticker_actions
        if action.get("confidence") is not None
    ]
    if confidences:
        return max(confidences)
    if ticker_has_specific_data:
        return float(analysis.get("confidence") or 0)
    return 0


def _ticker_supporting_evidence(
    analysis: dict[str, Any],
    ticker_actions: list[dict[str, Any]],
) -> list[str]:
    return [
        evidence
        for action in ticker_actions
        for evidence in action.get("evidence") or []
    ]


def _best_price_target(targets: list[dict[str, Any]]) -> dict[str, Any] | None:
    numeric_targets = [target for target in targets if target.get("target_price") is not None]
    if not numeric_targets:
        return targets[0] if targets else None
    ranked = sorted(
        numeric_targets,
        key=lambda target: (
            _target_source_priority(target),
            _target_specificity_priority(target),
            str(target.get("created_at") or ""),
        ),
        reverse=True,
    )
    return ranked[0]


def _target_source_priority(target: dict[str, Any]) -> int:
    source = str(target.get("source") or target.get("provider") or "").lower()
    source_text = str(target.get("source_text") or "").lower()
    if "average" in source_text or "consensus" in source_text:
        return 3
    if source in {"zacks", "seeking_alpha"}:
        return 2
    return 1


def _target_specificity_priority(target: dict[str, Any]) -> int:
    source_text = str(target.get("source_text") or "").lower()
    if "highest" in source_text or "high " in source_text:
        return 0
    if "lowest" in source_text or "low " in source_text:
        return 0
    return 1


def _price_target_summary(target: dict[str, Any] | None) -> str:
    if not target:
        return "not extracted"
    price = target.get("target_price")
    if price is None:
        return _clean(target.get("source_text") or "target mentioned")
    source_text = _clean(target.get("source_text"))
    rendered = f"{_clean(target.get('currency') or 'USD')} {price:g}"
    return f"{rendered} - {source_text}" if source_text else rendered


def _last_close_summary(last_close: Any) -> str:
    if last_close is None:
        return "not fetched"
    return f"USD {float(last_close):.2f}"


def _upside_downside_summary(target: dict[str, Any] | None, last_close: Any) -> str:
    if target is None:
        return "needs target"
    price = target.get("target_price")
    if price is None:
        return "needs numeric target"
    if last_close is None:
        return "needs last close"
    last_close_float = float(last_close)
    if last_close_float == 0:
        return "needs valid last close"
    diff = (float(price) - last_close_float) / last_close_float
    return f"{diff:+.1%}"


def _rating_value(
    ratings: list[dict[str, Any]],
    provider: str,
    rating_type: str,
    asset_type: Any = None,
) -> str:
    failed = None
    for rating in ratings:
        if rating.get("provider") == provider and rating.get("rating_type") == rating_type:
            if rating.get("status") == "failed":
                failed = rating
                continue
            value = _clean(rating.get("rating"))
            score = _format_score(rating.get("score"))
            suffix = _rating_origin_suffix(rating)
            if score is not None:
                rendered = f"{value} ({score})" if value else ""
                return f"{rendered}{suffix}" if rendered else _missing_rating_text()
            return f"{value}{suffix}" if value else _missing_rating_text()
    if failed is not None:
        return _failed_rating_text()
    return _missing_rating_text(provider=provider, rating_type=rating_type, asset_type=asset_type)


def _rating_target_value(
    ratings: list[dict[str, Any]],
    provider: str,
    polygon_last_close: Any = None,
    asset_type: Any = None,
) -> str:
    failed = None
    not_applicable = None
    for rating in ratings:
        if rating.get("provider") != provider:
            continue
        if rating.get("status") == "not_applicable" and rating.get("rating_type") == "price_target":
            not_applicable = rating
            continue
        if rating.get("status") == "failed" and rating.get("rating_type") == "price_target":
            failed = rating
            continue
        if rating.get("rating_type") != "price_target":
            continue
        target = rating.get("price_target")
        if target is None:
            continue
        currency = _clean(rating.get("currency") or "USD")
        text = f"{currency} {float(target):g}{_rating_origin_suffix(rating)}"
        details = []
        polygon_upside = _target_upside_pct(target, polygon_last_close)
        if polygon_upside is not None:
            details.append(f"Polygon {polygon_upside:+.1f}%")
        else:
            details.append("Polygon needs close")
        source_upside = rating.get("source_reported_upside_pct")
        if source_upside is not None:
            source_note = f"source {float(source_upside):+.2f}%"
            source_last_close = rating.get("source_last_close")
            implied_last_close = rating.get("implied_last_close_from_reported_upside")
            if source_last_close is not None:
                source_note += f" vs source close {currency} {float(source_last_close):.2f}"
            elif implied_last_close is not None:
                source_note += f" vs implied close {currency} {float(implied_last_close):.2f}"
            details.append(source_note)
        if details:
            return f"{text} ({'; '.join(details)})"
        return text
    if failed is not None:
        return _failed_rating_text()
    if not_applicable is not None:
        return "not applicable"
    return _missing_rating_text(provider=provider, rating_type="price_target", asset_type=asset_type)


def _investing_records(
    ratings: list[dict[str, Any]],
    data_type: str | None = None,
) -> list[dict[str, Any]]:
    records = [
        rating
        for rating in ratings
        if rating.get("provider") == "investing_pro"
        and (data_type is None or rating.get("rating_type") == data_type)
    ]
    return records


def _investing_first_ready(
    ratings: list[dict[str, Any]],
    data_type: str,
) -> dict[str, Any] | None:
    for record in _investing_records(ratings, data_type):
        if record.get("status") not in {"failed", "not_applicable"}:
            return record
    return None


def _investing_has_failed(
    ratings: list[dict[str, Any]],
    data_type: str,
) -> bool:
    return any(record.get("status") == "failed" for record in _investing_records(ratings, data_type))


def _investing_health_value(ratings: list[dict[str, Any]]) -> str:
    record = _investing_first_ready(ratings, "overview")
    if record:
        health = _clean(record.get("financial_health") or record.get("rating"))
        fair_value = _format_investing_value(record.get("fair_value"))
        analyst_sentiment = _clean(record.get("analyst_sentiment"))
        parts = [health]
        if fair_value:
            parts.append(f"fair value {fair_value}")
        if analyst_sentiment:
            parts.append(f"analysts {analyst_sentiment}")
        return "; ".join(part for part in parts if part) or "overview fetched"
    if _investing_has_failed(ratings, "overview"):
        return _failed_rating_text()
    return _missing_rating_text(provider="investing_pro", rating_type="overview")


def _investing_fair_value(ratings: list[dict[str, Any]], polygon_last_close: Any = None) -> str:
    record = _investing_first_ready(ratings, "forecast") or _investing_first_ready(ratings, "overview")
    if record:
        fair_value = _format_investing_value(record.get("fair_value"))
        if not fair_value:
            return "not extracted"
        details = []
        polygon_upside = _target_upside_pct(_investing_numeric(record.get("fair_value")), polygon_last_close)
        if polygon_upside is not None:
            details.append(f"Polygon {polygon_upside:+.1f}%")
        source_upside = record.get("fair_value_upside_pct")
        if source_upside is not None:
            details.append(f"source {float(source_upside):+.1f}%")
        elif record.get("fair_value_upside"):
            details.append(f"source {_format_investing_value(record.get('fair_value_upside'))}")
        uncertainty = _clean(record.get("fair_value_uncertainty"))
        if uncertainty:
            details.append(f"uncertainty {uncertainty}")
        model_count = record.get("fair_value_model_count")
        if model_count is not None:
            details.append(f"{int(model_count)} models")
        return f"{fair_value} ({'; '.join(details)})" if details else fair_value
    if _investing_has_failed(ratings, "forecast") or _investing_has_failed(ratings, "overview"):
        return _failed_rating_text()
    return _missing_rating_text(provider="investing_pro", rating_type="forecast")


def _investing_analyst_target(ratings: list[dict[str, Any]], polygon_last_close: Any = None) -> str:
    record = _investing_first_ready(ratings, "forecast")
    if record:
        target = record.get("analyst_target_average")
        if target is None:
            return "not extracted"
        details = []
        polygon_upside = _target_upside_pct(target, polygon_last_close)
        if polygon_upside is not None:
            details.append(f"Polygon {polygon_upside:+.1f}%")
        low = record.get("analyst_target_low")
        high = record.get("analyst_target_high")
        if low is not None and high is not None:
            details.append(f"range USD {float(low):g}-{float(high):g}")
        rating_count = record.get("rating_count")
        if rating_count is not None:
            details.append(f"{int(rating_count)} ratings")
        consensus = _clean(record.get("rating"))
        if consensus and consensus != "Forecast":
            details.append(consensus)
        return f"USD {float(target):g} ({'; '.join(details)})" if details else f"USD {float(target):g}"
    overview = _investing_first_ready(ratings, "overview")
    if overview:
        target_value = _format_investing_value(overview.get("analyst_price_target"))
        if not target_value:
            return "not extracted"
        details = []
        polygon_upside = _target_upside_pct(_investing_numeric(overview.get("analyst_price_target")), polygon_last_close)
        if polygon_upside is not None:
            details.append(f"Polygon {polygon_upside:+.1f}%")
        sentiment = _clean(overview.get("analyst_sentiment"))
        if sentiment:
            details.append(sentiment)
        return f"{target_value} ({'; '.join(details)})" if details else target_value
    if _investing_has_failed(ratings, "forecast") or _investing_has_failed(ratings, "overview"):
        return _failed_rating_text()
    return _missing_rating_text(provider="investing_pro", rating_type="forecast")


def _investing_ratio_summary(ratings: list[dict[str, Any]]) -> str:
    record = _investing_first_ready(ratings, "ratios")
    if record:
        categories = record.get("categories") or {}
        preferred = [
            ("valuation_ratios", "Valuation"),
            ("profitability", "Profitability"),
            ("growth", "Growth"),
            ("financial_strength", "Financial strength"),
        ]
        parts: list[str] = []
        for key, label in preferred:
            for item in categories.get(key) or []:
                company = _format_investing_value(item.get("company"))
                industry = _format_investing_value(item.get("industry"))
                metric = _clean(item.get("metric"))
                if metric and company:
                    comparison = f" vs industry {industry}" if industry else ""
                    parts.append(f"{label} {metric}: {company}{comparison}")
                    break
            if len(parts) == 2:
                break
        return "; ".join(parts) if parts else "ratios fetched"
    overview = _investing_first_ready(ratings, "overview")
    metrics = (overview or {}).get("metrics") or {}
    parts = [
        f"{label}: {_format_investing_value(metrics.get(label))}"
        for label in ["P/E Ratio", "Revenue", "EPS", "Beta"]
        if _format_investing_value(metrics.get(label))
    ]
    if parts:
        return "; ".join(parts)
    if _investing_has_failed(ratings, "ratios"):
        return _failed_rating_text()
    return _missing_rating_text(provider="investing_pro", rating_type="ratios")


def _format_investing_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        raw = _clean(value.get("raw"))
        numeric = value.get("value")
        unit = value.get("unit")
        if numeric is None:
            return raw
        if unit == "percent":
            return f"{float(numeric):g}%"
        if unit == "multiple":
            return f"{float(numeric):g}x"
        if raw.startswith("$"):
            return f"USD {float(numeric):g}"
        return f"{float(numeric):g}"
    if isinstance(value, (int, float)):
        return f"USD {float(value):g}"
    return _clean(value)


def _investing_numeric(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratings_with_origin(ratings: list[dict[str, Any]], origin: str) -> list[dict[str, Any]]:
    return [_rating_with_origin(rating, origin) for rating in ratings]


def _rating_with_origin(rating: dict[str, Any], origin: str) -> dict[str, Any]:
    rendered = dict(rating)
    rendered.setdefault("origin", origin)
    return rendered


def _rating_origin_suffix(rating: dict[str, Any]) -> str:
    if rating.get("origin") == "article":
        return " (article)"
    return ""


def _failed_rating_text() -> str:
    return "fetch failed"


def _missing_rating_text(
    provider: str | None = None,
    rating_type: str | None = None,
    asset_type: Any = None,
) -> str:
    normalized_asset_type = _clean(asset_type).lower()
    if normalized_asset_type == "etf" and rating_type == "price_target":
        return "not applicable for ETF"
    return "source page not fetched"


def _format_score(score: Any) -> str | None:
    if score is None:
        return None
    if isinstance(score, (int, float)):
        return f"{score:g}"
    text = _clean(score)
    if not text:
        return None
    try:
        return f"{float(text):g}"
    except ValueError:
        return text


def _target_upside_pct(target: Any, last_close: Any) -> float | None:
    if target is None or last_close is None:
        return None
    last_close_float = float(last_close)
    if last_close_float == 0:
        return None
    return (float(target) - last_close_float) / last_close_float * 100


def _actionable_signal_summary(signals: list[dict[str, Any]]) -> str:
    if not signals:
        return "not extracted"
    rendered: list[str] = []
    seen: set[str] = set()
    for signal in signals:
        signal_type = _clean(signal.get("signal_type") or "other").replace("_", " ")
        label = _clean(signal.get("signal"))
        value = _clean(signal.get("value"))
        direction = _clean(signal.get("direction"))
        parts = [signal_type.title()]
        if label:
            parts.append(label)
        if value:
            parts.append(value)
        if direction and direction != "unclear":
            parts.append(direction)
        text = ": ".join([parts[0], " / ".join(parts[1:])]) if len(parts) > 1 else parts[0]
        if text not in seen:
            rendered.append(text)
            seen.add(text)
        if len(rendered) == 3:
            break
    return "; ".join(rendered) if rendered else "not extracted"


def _polygon_reference_summary(reference: dict[str, Any]) -> str:
    parts = [
        _clean(reference.get("type") or ""),
        _clean(reference.get("market") or ""),
        _clean(reference.get("locale") or ""),
    ]
    value = " / ".join(part for part in parts if part)
    return value or "not available"


def _suggested_action(stance: str, confidence: float, card: dict[str, Any]) -> str:
    has_risks = bool(card.get("risks"))
    if stance == "sell_watch" and confidence >= 0.7:
        return "Review immediately"
    if stance == "buy_watch" and confidence >= 0.8:
        return "Review immediately"
    if stance == "buy_watch":
        return "Add to watchlist"
    if stance == "hold":
        return "Hold / monitor"
    if has_risks:
        return "Monitor risk"
    return "Ignore / low evidence"


def _card_priority_score(stance: str, confidence: float, card: dict[str, Any]) -> float:
    stance_weight = {"sell_watch": 5, "buy_watch": 4, "hold": 2, "unclear": 1}.get(stance, 1)
    risk_weight = 1 if card.get("risks") else 0
    target_weight = 1 if card.get("price_targets") else 0
    return stance_weight + confidence + risk_weight + target_weight


def _ticker_article_summary(
    article: dict[str, Any],
    ticker: str,
    *,
    ticker_actions: list[dict[str, Any]] | None = None,
    ticker_signals: list[dict[str, Any]] | None = None,
    ticker_targets: list[dict[str, Any]] | None = None,
    ticker_ratings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    analysis = _analysis(article)
    ticker_actions = ticker_actions if ticker_actions is not None else [
        action
        for action in analysis.get("actionable_data") or []
        if normalize_ticker(str(action.get("ticker") or "")) == normalize_ticker(ticker)
    ]
    ticker_signals = ticker_signals if ticker_signals is not None else [
        signal
        for signal in analysis.get("actionable_signals") or []
        if normalize_ticker(str(signal.get("ticker") or "")) == normalize_ticker(ticker)
    ]
    ticker_targets = ticker_targets if ticker_targets is not None else [
        target
        for target in analysis.get("price_targets") or []
        if normalize_ticker(str(target.get("ticker") or "")) == normalize_ticker(ticker)
    ]
    ticker_ratings = ticker_ratings if ticker_ratings is not None else [
        rating
        for rating in analysis.get("rating_snapshots") or []
        if normalize_ticker(str(rating.get("ticker") or "")) == normalize_ticker(ticker)
    ]
    content = article.get("content") or {}
    return {
        "title": _title(article),
        "source_key": article.get("source_key"),
        "url": article.get("normalized_url"),
        "brief": _ticker_specific_article_brief(
            analysis,
            ticker,
            ticker_actions,
            ticker_signals,
            ticker_targets,
            ticker_ratings,
        ),
        "stance": analysis.get("stance") or "unclear",
        "sentiment": analysis.get("sentiment") or "unclear",
        "recommendation": analysis.get("recommendation") or "unclear",
        "confidence": analysis.get("confidence") or 0,
        "evidence": _ticker_supporting_evidence(analysis, ticker_actions),
        "catalysts": [item for action in ticker_actions for item in (action.get("catalysts") or [])],
        "risks": [item for action in ticker_actions for item in (action.get("risks") or [])],
        "signals": ticker_signals,
        "text_char_count": content.get("text_char_count") or 0,
    }


def _ticker_specific_article_brief(
    analysis: dict[str, Any],
    ticker: str,
    ticker_actions: list[dict[str, Any]],
    ticker_signals: list[dict[str, Any]],
    ticker_targets: list[dict[str, Any]],
    ticker_ratings: list[dict[str, Any]],
) -> dict[str, Any]:
    primary_action = ticker_actions[0] if ticker_actions else {}
    theme = _clean(primary_action.get("theme_summary"))
    if not theme:
        theme = _legacy_ticker_theme(analysis, ticker, ticker_actions)

    key_points: list[Any] = list(primary_action.get("key_points") or [])
    key_points.extend(primary_action.get("financial_details") or [])
    notes: list[Any] = []
    for action in ticker_actions:
        notes.extend(action.get("evidence") or [])
        notes.extend(action.get("catalysts") or [])
        notes.extend(action.get("risks") or [])
        notes.append(action.get("source_text"))
        notes.append(action.get("rationale"))
        notes.append(action.get("reason"))
    for signal in ticker_signals:
        signal_text = " / ".join(
            _clean(part)
            for part in [
                signal.get("signal_type"),
                signal.get("signal"),
                signal.get("value"),
                signal.get("direction"),
                signal.get("source_text"),
            ]
            if _clean(part)
        )
        notes.append(signal_text)
        key_points.append(signal_text)
    for target in ticker_targets:
        target_text = " / ".join(
                _clean(part)
                    for part in [
                        "Price target",
                        _price_target_summary(target),
                        target.get("timeframe"),
                        target.get("source_text"),
                    ]
                if _clean(part)
            )
        notes.append(target_text)
        key_points.append(target_text)
    for rating in ticker_ratings:
        rating_text = " / ".join(
            _clean(part)
            for part in [
                rating.get("provider"),
                rating.get("rating_type"),
                rating.get("rating"),
                rating.get("score"),
                rating.get("source_text"),
            ]
            if _clean(part)
        )
        notes.append(rating_text)
        key_points.append(rating_text)
    cleaned = _unique_text(notes)
    if not theme:
        theme = cleaned[0] if cleaned else "Ticker-specific evidence was not retained for this source article."

    recommendation = _clean(primary_action.get("source_recommendation_text"))
    if not recommendation:
        normalized = _clean(primary_action.get("recommendation") or analysis.get("recommendation") or "unclear")
        timeframe = _clean(primary_action.get("timeframe"))
        recommendation = f"The extracted article recommendation is {normalized}"
        if timeframe and timeframe.lower() != "unclear":
            recommendation += f" over {timeframe}"
        recommendation += ". The source rationale was not separately retained."

    investor_actions = _unique_text(primary_action.get("investor_actions") or [])
    if not investor_actions:
        investor_actions = _fallback_investor_actions(primary_action, ticker_targets)
    follow_up_checks = _unique_text(primary_action.get("follow_up_checks") or [])
    if not follow_up_checks:
        follow_up_checks = _fallback_follow_up_checks(primary_action, ticker_signals)

    return {
        "theme": _truncate(theme, limit=700),
        "key_points": _unique_text(key_points + cleaned)[:5],
        "source_recommendation": _truncate(recommendation, limit=420),
        "investor_actions": investor_actions[:3],
        "follow_up_checks": follow_up_checks[:3],
    }


def _legacy_ticker_theme(
    analysis: dict[str, Any],
    ticker: str,
    ticker_actions: list[dict[str, Any]],
) -> str:
    summary = _clean(analysis.get("summary"))
    mentioned_tickers = {
        normalize_ticker(str(item.get("ticker") if isinstance(item, dict) else item))
        for item in (
            analysis.get("mentioned_ticker_details")
            or analysis.get("mentioned_tickers")
            or []
        )
    }
    if summary and mentioned_tickers == {normalize_ticker(ticker)}:
        return summary
    for action in ticker_actions:
        candidates = list(action.get("evidence") or []) + list(action.get("financial_details") or [])
        if candidates:
            return "; ".join(_unique_text(candidates[:3]))
    return ""


def _fallback_investor_actions(
    action: dict[str, Any],
    ticker_targets: list[dict[str, Any]],
) -> list[str]:
    recommendation = _clean(action.get("recommendation") or "unclear").lower()
    if recommendation in {"buy", "watch"}:
        result = ["Review valuation and position sizing before acting on the bullish thesis."]
    elif recommendation in {"sell", "avoid"}:
        result = ["Reassess the holding against the cited downside risks and the original investment thesis."]
    elif recommendation == "hold":
        result = ["Maintain the current view while checking whether the cited catalysts or risks are changing."]
    else:
        result = ["Treat this article as a research lead until its central claims are independently verified."]
    if ticker_targets:
        result.append("Compare the article's price target with the Polygon last close and your required return.")
    return result


def _fallback_follow_up_checks(
    action: dict[str, Any],
    ticker_signals: list[dict[str, Any]],
) -> list[str]:
    checks = list(action.get("risks") or []) + list(action.get("catalysts") or [])
    checks.extend(
        "Monitor " + _clean(signal.get("signal"))
        for signal in ticker_signals
        if _clean(signal.get("signal"))
    )
    return _unique_text(checks) or ["Verify the thesis against the next material company update."]


def _ticker_article_notes(articles: list[dict[str, Any]]) -> str:
    if not articles:
        return "<p class='muted'>No source article notes were retained for this ticker.</p>"
    return "".join(_ticker_article_note(article) for article in articles)


def _ticker_article_note(article: dict[str, Any]) -> str:
    source_url = _clean(article.get("url"))
    link = f'<a href="{_e(source_url)}">source link</a>' if source_url else "<span class='muted'>No source URL</span>"
    brief = article.get("brief") or {}
    key_points = _sentence_list(brief.get("key_points") or [], "No additional key points were retained.")
    investor_actions = _sentence_list(brief.get("investor_actions") or [], "No specific investor action was supported.")
    follow_up_checks = _sentence_list(brief.get("follow_up_checks") or [], "No specific follow-up was retained.")
    return f"""
      <div class="article-note">
        <div class="article-note-title">{_e(article.get("title"))}</div>
        <div class="article-note-meta">{_e(article.get("source_key"))} - {_e(_signal_from_stance(article.get("stance")))} - {_e(article.get("sentiment"))} / {_e(article.get("recommendation"))} - {_e(_percent(article.get("confidence") or 0))} confidence - {_e(article.get("text_char_count") or 0)} chars</div>
        <div class="article-note-summary">
          <b>Main theme:</b> {_e(brief.get('theme'))}
          <b>Key points:</b> {_e(key_points)}
          <b>Article recommendation:</b> {_e(brief.get('source_recommendation'))}
          <b>Investor actions:</b> {_e(investor_actions)}
          <b>Follow up:</b> {_e(follow_up_checks)}
        </div>
        <div class="mini">{link}</div>
      </div>"""


def _sentence_list(items: list[Any], empty_text: str) -> str:
    cleaned = _unique_text(items)
    if not cleaned:
        return empty_text
    return " ".join(f"{index}. {item}" for index, item in enumerate(cleaned, start=1))


def _bullet_list(items: list[Any], empty_text: str, limit: int = 5) -> str:
    cleaned = _unique_text(items)[:limit]
    if not cleaned:
        return f"<p class='muted'>{_e(empty_text)}</p>"
    return "<ul class='note-list'>" + "".join(f"<li>{_e(item)}</li>" for item in cleaned) + "</ul>"


def _inline_summary(items: list[Any], empty_text: str, limit: int = 3) -> str:
    cleaned = _unique_text(items)[:limit]
    return "; ".join(cleaned) if cleaned else empty_text


def _truncate(value: Any, limit: int) -> str:
    text = _clean(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _unique_text(items: list[Any]) -> list[str]:
    rendered: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _clean(item)
        key = text.lower()
        if text and key not in seen:
            rendered.append(text)
            seen.add(key)
    return rendered


def _confidence_summary(values: list[Any]) -> str:
    numeric = [float(value) for value in values if value is not None]
    if not numeric:
        return "-"
    if len(numeric) == 1:
        return _percent(numeric[0])
    return f"{_percent(min(numeric))} - {_percent(max(numeric))}"


def _contradiction_summary(card: dict[str, Any]) -> str:
    recommendations = {str(value).lower() for value in card.get("recommendations") or [] if value}
    stances = {str(value).lower() for value in card.get("stances") or [] if value}
    has_bullish = bool(recommendations & {"buy", "watch", "strong_buy"} or stances & {"buy_watch"})
    has_bearish = bool(recommendations & {"sell", "avoid", "reduce"} or stances & {"sell_watch", "avoid"})
    if has_bullish and has_bearish:
        return "Conflicting article signals were detected and should be reviewed manually."
    return "No direct buy-versus-sell contradiction detected across this ticker's articles."


def _signal_from_stance(stance: Any) -> str:
    normalized = str(stance or "unclear").lower()
    if normalized == "buy_watch":
        return "Buy Watch"
    if normalized == "sell_watch":
        return "Sell Watch"
    if normalized == "hold":
        return "Hold"
    return "Unclear"


def _most_common(values: list[str]) -> str | None:
    cleaned = [value for value in values if value]
    return Counter(cleaned).most_common(1)[0][0] if cleaned else None


def _analysis(article: dict[str, Any]) -> dict[str, Any]:
    return article.get("analysis") or {}


def _is_usable_article(article: dict[str, Any]) -> bool:
    return bool(article.get("analysis")) and not _has_pdf_quality_issue(article)


def _has_pdf_quality_issue(article: dict[str, Any]) -> bool:
    content = article.get("content") or {}
    if _is_blocked_article(article):
        return True
    if content.get("fetch_status") not in {"fetched", "email_fallback"}:
        return True
    return False


def _is_blocked_article(article: dict[str, Any]) -> bool:
    content = article.get("content") or {}
    title = str(content.get("title") or "").lower()
    failure_reason = str(content.get("failure_reason") or "").lower()
    return (
        content.get("fetch_status") == "blocked"
        or "access to this page has been denied" in title
        or "human verification" in failure_reason
        or "source blocked" in failure_reason
    )


def _title(article: dict[str, Any]) -> str:
    return _clean((article.get("content") or {}).get("title") or article.get("subject") or "Untitled article")


def _portfolio_tickers(article: dict[str, Any]) -> list[str]:
    return _article_tickers(article, portfolio_only=True)


def _article_tickers(article: dict[str, Any], portfolio_only: bool) -> list[str]:
    return [
        _clean(ticker.get("ticker")).upper()
        for ticker in _analysis(article).get("mentioned_ticker_details") or []
        if ticker.get("in_portfolio") or not portfolio_only
    ]


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
