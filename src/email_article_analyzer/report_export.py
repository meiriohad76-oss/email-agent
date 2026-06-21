from collections import defaultdict
from typing import Any


LOW_CONFIDENCE_THRESHOLD = 0.70
ETF_OR_MACRO_TICKERS = {
    "DIA",
    "GLD",
    "IBIT",
    "IVV",
    "IWM",
    "NDX",
    "QQQ",
    "SLV",
    "SPX",
    "SPY",
    "TLT",
    "VOO",
}
BUY_STANCES = {"buy_watch", "watch", "buy", "strong_buy"}
SELL_STANCES = {"sell_watch", "sell", "avoid", "reduce"}


def build_run_markdown_report(
    run: dict[str, Any],
    counts: dict[str, int],
    events: list[dict[str, Any]],
    articles: list[dict[str, Any]],
) -> str:
    analyzed_articles = [article for article in articles if article.get("analysis")]
    portfolio_articles = [
        article for article in analyzed_articles if _has_portfolio_ticker(article)
    ]
    non_portfolio_articles = [
        article
        for article in analyzed_articles
        if _is_buy_or_watch(article) and not _has_portfolio_ticker(article)
    ]
    buy_watch_articles = [
        article for article in analyzed_articles if _is_buy_or_watch(article)
    ]
    sell_watch_articles = [
        article for article in analyzed_articles if _is_sell_or_risk(article)
    ]
    macro_articles = [
        article for article in analyzed_articles if _mentions_macro_or_etf_ticker(article)
    ]
    low_quality_articles = [
        article for article in articles if _has_quality_issue(article)
    ]
    conflict_lines = _build_conflict_lines(analyzed_articles)

    lines = [
        f"# Daily Stock Article Intelligence - Run #{run['id']}",
        "",
        "Generated from analyzed unread email article links. This report is informational only and is not financial advice.",
        "",
        "## Executive Summary",
        (
            f"- Run status: {_value(run.get('status'))}; "
            f"{counts.get('gmail_messages', 0)} emails; "
            f"{counts.get('article_links', len(articles))} article links; "
            f"{len(analyzed_articles)} analyzed articles."
        ),
        (
            f"- Portfolio-related articles: {len(portfolio_articles)}; "
            f"buy/watch ideas: {len(buy_watch_articles)}; "
            f"sell-watch/risk alerts: {len(sell_watch_articles)}; "
            f"quality issues: {len(low_quality_articles)}."
        ),
        (
            f"- Models: extraction {_value(run.get('extraction_model'))}; "
            f"summary {_value(run.get('summary_model'))}."
        ),
        "",
        "## Key Findings",
    ]
    lines.extend(_section_or_empty(_article_lines(portfolio_articles[:5]), "No portfolio-linked articles were analyzed."))
    lines.extend(["", "## Portfolio Impact"])
    lines.extend(_section_or_empty(_article_lines(portfolio_articles), "No analyzed article mentioned a current portfolio ticker."))
    lines.extend(["", "## Buy-Watch Ideas"])
    lines.extend(_section_or_empty(_article_lines(buy_watch_articles), "No buy/watch ideas were identified."))
    lines.extend(["", "## Sell-Watch / Risk Alerts"])
    lines.extend(_section_or_empty(_article_lines(sell_watch_articles), "No sell-watch or avoid alerts were identified."))
    lines.extend(["", "## Conflicting Coverage"])
    lines.extend(_section_or_empty(conflict_lines, "No ticker had conflicting recommendations in this run."))
    lines.extend(["", "## Non-Portfolio Opportunities"])
    lines.extend(_section_or_empty(_article_lines(non_portfolio_articles), "No non-portfolio buy/watch ideas were identified."))
    lines.extend(["", "## Macro / ETF Themes"])
    lines.extend(_section_or_empty(_article_lines(macro_articles), "No macro or ETF-linked articles were identified."))
    lines.extend(["", "## Low-Quality Or Failed Items"])
    lines.extend(_section_or_empty(_quality_lines(low_quality_articles), "No low-confidence or failed items were detected."))
    lines.extend(["", "## Recommended Next Steps"])
    lines.extend(_recommended_next_steps(portfolio_articles, buy_watch_articles, sell_watch_articles, low_quality_articles))
    lines.extend(["", "## Further Questions"])
    lines.extend(
        [
            "- Which portfolio holdings should be promoted to a higher-priority review queue?",
            "- Which recurring sources produce the most useful evidence versus low-quality extraction noise?",
            "- Should non-portfolio ideas be routed into a separate watchlist before they appear beside active holdings?",
        ]
    )
    lines.extend(["", "## Caveats And Assumptions"])
    lines.extend(_caveats(events))
    lines.append("")
    return "\n".join(lines)


def _article_lines(articles: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for article in articles:
        analysis = article.get("analysis") or {}
        title = _article_title(article)
        tickers = _format_tickers(analysis)
        confidence = _format_percent(analysis.get("confidence"))
        lines.append(
            (
                f"- **{_escape_markdown(title)}** | {tickers} | "
                f"Stance: {_value(analysis.get('stance'))} | "
                f"Sentiment: {_value(analysis.get('sentiment'))} | "
                f"Recommendation: {_value(analysis.get('recommendation'))} | "
                f"Confidence: {confidence}"
            )
        )
        summary = analysis.get("summary")
        if summary:
            lines.append(f"  - Summary: {_escape_markdown(str(summary))}")
        price_targets = _format_price_targets(analysis.get("price_targets") or [])
        if price_targets:
            lines.append(f"  - Price targets: {price_targets}")
        actionable = _format_actionable_data(analysis.get("actionable_data") or [])
        if actionable:
            lines.append(f"  - Actionable data: {actionable}")
        evidence = (analysis.get("supporting_evidence") or [])[:2]
        if evidence:
            lines.append(
                "  - Evidence: "
                + "; ".join(_escape_markdown(str(item)) for item in evidence)
            )
        if article.get("normalized_url"):
            lines.append(f"  - Link: {article['normalized_url']}")
    return lines


def _quality_lines(articles: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for article in articles:
        reasons = _quality_reasons(article, include_default=True)
        lines.append(f"- **{_escape_markdown(_article_title(article))}** | {', '.join(reasons)}")
        if article.get("normalized_url"):
            lines.append(f"  - Link: {article['normalized_url']}")
    return lines


def _quality_reasons(article: dict[str, Any], include_default: bool = False) -> list[str]:
    reasons: list[str] = []
    content = article.get("content") or {}
    analysis = article.get("analysis") or {}
    detection_confidence = article.get("detection_confidence")
    if detection_confidence is not None and float(detection_confidence) < LOW_CONFIDENCE_THRESHOLD:
        reasons.append(f"{_format_percent(detection_confidence)} link confidence")
    if not content:
        reasons.append("content not fetched")
    elif content.get("fetch_status") not in {"fetched", "email_fallback"}:
        reasons.append(f"content {content.get('fetch_status')}")
    if content.get("failure_reason"):
        reasons.append(str(content["failure_reason"]))
    if not analysis:
        reasons.append("analysis missing")
    elif (analysis.get("confidence") or 0) < LOW_CONFIDENCE_THRESHOLD:
        reasons.append(f"{_format_percent(analysis.get('confidence'))} analysis confidence")
    if include_default and not reasons:
        return ["needs review"]
    return reasons


def _has_quality_issue(article: dict[str, Any]) -> bool:
    return bool(_quality_reasons(article))


def _build_conflict_lines(articles: list[dict[str, Any]]) -> list[str]:
    by_ticker: dict[str, set[str]] = defaultdict(set)
    for article in articles:
        analysis = article.get("analysis") or {}
        recommendation = str(analysis.get("recommendation") or analysis.get("stance") or "unclear")
        for detail in analysis.get("mentioned_ticker_details") or []:
            ticker = str(detail.get("ticker") or "").strip().upper()
            if ticker:
                by_ticker[ticker].add(recommendation)
    return [
        f"- {ticker}: {', '.join(sorted(recommendations))}"
        for ticker, recommendations in sorted(by_ticker.items())
        if len(recommendations) > 1
    ]


def _recommended_next_steps(
    portfolio_articles: list[dict[str, Any]],
    buy_watch_articles: list[dict[str, Any]],
    sell_watch_articles: list[dict[str, Any]],
    low_quality_articles: list[dict[str, Any]],
) -> list[str]:
    steps = []
    if portfolio_articles:
        steps.append("- Review portfolio-linked articles first, especially those with confidence above 70% and at least two evidence points.")
    if sell_watch_articles:
        steps.append("- Escalate sell-watch or avoid alerts into a risk review before acting on new buy ideas.")
    if buy_watch_articles:
        steps.append("- For buy/watch ideas, verify price targets and catalysts against Polygon market data before any trade decision.")
    if low_quality_articles:
        steps.append("- Re-run or manually inspect low-quality items before using them in an investment decision.")
    return steps or ["- No immediate action items were generated from this run."]


def _caveats(events: list[dict[str, Any]]) -> list[str]:
    caveats = [
        "- The report summarizes extracted article content and model output; it does not verify every claim against filings or live market data.",
        "- Portfolio membership is based on the currently uploaded watchlist at report generation time.",
        "- Recommendations are article-derived classifications, not personalized investment advice.",
    ]
    warning_events = [
        event for event in events if event.get("severity") in {"warning", "error"}
    ][:5]
    for event in warning_events:
        caveats.append(
            f"- Run event: {_value(event.get('stage'))} / {_value(event.get('event_type'))}: {_value(event.get('message'))}"
        )
    return caveats


def _section_or_empty(lines: list[str], empty_message: str) -> list[str]:
    return lines if lines else [f"- {empty_message}"]


def _has_portfolio_ticker(article: dict[str, Any]) -> bool:
    analysis = article.get("analysis") or {}
    return any(
        detail.get("in_portfolio")
        for detail in analysis.get("mentioned_ticker_details") or []
    )


def _is_buy_or_watch(article: dict[str, Any]) -> bool:
    analysis = article.get("analysis") or {}
    return _normalized_recommendation(analysis) in BUY_STANCES or _normalized_stance(analysis) in BUY_STANCES


def _is_sell_or_risk(article: dict[str, Any]) -> bool:
    analysis = article.get("analysis") or {}
    return _normalized_recommendation(analysis) in SELL_STANCES or _normalized_stance(analysis) in SELL_STANCES


def _normalized_recommendation(analysis: dict[str, Any]) -> str:
    return str(analysis.get("recommendation") or "").lower()


def _normalized_stance(analysis: dict[str, Any]) -> str:
    return str(analysis.get("stance") or "").lower()


def _mentions_macro_or_etf_ticker(article: dict[str, Any]) -> bool:
    analysis = article.get("analysis") or {}
    tickers = {
        str(detail.get("ticker") or "").upper()
        for detail in analysis.get("mentioned_ticker_details") or []
    }
    return bool(tickers & ETF_OR_MACRO_TICKERS)


def _article_title(article: dict[str, Any]) -> str:
    content = article.get("content") or {}
    return str(content.get("title") or article.get("subject") or "Untitled article")


def _format_tickers(analysis: dict[str, Any]) -> str:
    details = analysis.get("mentioned_ticker_details") or []
    if details:
        return ", ".join(
            f"{detail.get('ticker')} ({'portfolio' if detail.get('in_portfolio') else 'not portfolio'})"
            for detail in details
        )
    tickers = analysis.get("mentioned_tickers") or []
    return ", ".join(str(ticker) for ticker in tickers) or "No ticker"


def _format_price_targets(price_targets: list[Any]) -> str:
    formatted = []
    for target in price_targets:
        if not isinstance(target, dict):
            continue
        ticker = _value(target.get("ticker"), "Ticker")
        price = target.get("target_price")
        currency = str(target.get("currency") or "").strip()
        timeframe = str(target.get("timeframe") or "").strip()
        price_text = "not specified" if price is None else f"{currency} {price}".strip()
        formatted.append(" ".join(part for part in [ticker, price_text, timeframe] if part))
    return "; ".join(formatted)


def _format_actionable_data(items: list[Any]) -> str:
    formatted = []
    for item in items:
        if not isinstance(item, dict):
            continue
        parts = [
            _value(item.get("ticker"), "Ticker"),
            f"recommendation {_value(item.get('recommendation'))}",
            f"sentiment {_value(item.get('sentiment'))}",
            f"timeframe {_value(item.get('timeframe'))}",
        ]
        catalysts = item.get("catalysts") or []
        risks = item.get("risks") or []
        details = item.get("financial_details") or []
        if catalysts:
            parts.append(f"catalysts {', '.join(map(str, catalysts))}")
        if risks:
            parts.append(f"risks {', '.join(map(str, risks))}")
        if details:
            parts.append(f"details {', '.join(map(str, details))}")
        formatted.append("; ".join(parts))
    return " | ".join(formatted)


def _format_percent(value: Any) -> str:
    if value is None:
        return "-"
    return f"{round(float(value) * 100)}%"


def _value(value: Any, fallback: str = "-") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def _escape_markdown(value: str) -> str:
    return value.replace("\n", " ").strip()
