from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from email_article_analyzer.watchlist import normalize_ticker


GRADE_PATTERN = re.compile(r"^[A-F](?:[+-])?$")
GRADE_SCORE = {
    "A+": 13,
    "A": 12,
    "A-": 11,
    "B+": 10,
    "B": 9,
    "B-": 8,
    "C+": 7,
    "C": 6,
    "C-": 5,
    "D+": 4,
    "D": 3,
    "D-": 2,
    "F": 1,
}
HORIZONS = ["current_quarter", "next_quarter", "current_year", "next_year"]


def parse_seeking_alpha_research(ticker: str, page_type: str, text: str) -> list[dict[str, Any]]:
    if page_type in {"valuation", "growth", "profitability", "momentum"}:
        record = _parse_sa_factor_page(ticker, page_type, text)
    elif page_type in {"income_statement", "cash_flow_statement"}:
        record = _parse_sa_statement(ticker, page_type, text)
    elif page_type == "peers":
        record = _parse_sa_peers(ticker, text)
    elif page_type == "estimates":
        record = _parse_sa_estimates(ticker, text)
    elif page_type == "revisions":
        record = _parse_sa_revisions(ticker, text)
    elif page_type in {"news", "analysis"}:
        record = _parse_news_listing(ticker, "seeking_alpha", page_type, text)
    else:
        record = None
    return [record] if record else []


def parse_investing_research(ticker: str, page_type: str, text: str) -> list[dict[str, Any]]:
    parsers = {
        "overview": _parse_investing_overview,
        "financial_summary": _parse_investing_financial_summary,
        "ratios": _parse_investing_ratios,
        "forecast": _parse_investing_forecast,
        "ownership": _parse_investing_ownership,
        "cash_flow_statement": _parse_investing_cash_flow,
        "news": lambda symbol, value: _parse_news_listing(symbol, "investing_pro", "news", value),
        "analysis": lambda symbol, value: _parse_news_listing(symbol, "investing_pro", "analysis", value),
        "options_chain": _parse_investing_options_chain,
    }
    parser = parsers.get(page_type)
    record = parser(ticker, text) if parser else None
    return [record] if record else []


def _parse_news_listing(
    ticker: str,
    provider: str,
    page_type: str,
    text: str,
) -> dict[str, Any] | None:
    items = []
    seen_urls = set()
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("EQUITY_NEWS_ITEM "):
            continue
        try:
            payload = json.loads(line.removeprefix("EQUITY_NEWS_ITEM "))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        title = str(payload.get("title") or "").strip()
        url = str(payload.get("url") or "").strip().split("#", 1)[0]
        if not title or not url or url in seen_urls:
            continue
        seen_urls.add(url)
        excerpt = str(payload.get("excerpt") or "").strip()
        items.append(
            {
                "title": title,
                "url": url,
                "published_at": str(payload.get("published_at") or "").strip() or None,
                "author": str(payload.get("author") or "").strip() or None,
                "author_rating": str(payload.get("author_rating") or "").strip() or None,
                "content_type": str(payload.get("content_type") or page_type).strip().lower(),
                "event_type": _classify_news_event(title, excerpt),
                "excerpt": excerpt or None,
            }
        )
    if not items:
        return None
    label = "Analyst articles" if page_type == "analysis" else "Recent news"
    return _record(
        ticker,
        provider,
        f"{page_type}_items",
        rating=label,
        score=len(items),
        extra={"content_type": page_type, "item_count": len(items), "items": items},
    )


def _classify_news_event(title: str, excerpt: str = "") -> str:
    value = f"{title} {excerpt}".lower()
    rules = [
        ("earnings", r"earnings|\beps\b|quarter results|revenue (?:of|beat|miss)"),
        ("guidance", r"guidance|outlook|forecast|raises? 20\d{2}|cuts? 20\d{2}"),
        ("analyst_action", r"price target|upgrade|downgrade|initiates?|maintains? .* (?:buy|sell|hold|overweight|underweight)"),
        ("regulatory", r"\bfda\b|regulator|approval|orphan drug|clinical hold"),
        ("clinical", r"phase [123]|clinical trial|topline|data readout|endpoint"),
        ("m_and_a", r"acquisition|merger|tender offer|acquires?|deal for"),
        ("capital_allocation", r"buyback|repurchase|dividend|debt offering|share offering"),
        ("management", r"appoints?|resigns?|chief executive|chief financial officer|ceo|cfo"),
        ("legal", r"lawsuit|litigation|investigation|settlement"),
    ]
    return next((event_type for event_type, pattern in rules if re.search(pattern, value)), "other")


def parse_zacks_detailed_estimates(ticker: str, text: str) -> list[dict[str, Any]]:
    compact = _compact(text)
    rank = _regex_int(compact, r"Zacks Rank\s+(?:More Info\s+)?(?:Hold|Buy|Sell|Strong Buy|Strong Sell)\s+([1-5])")
    style_match = re.search(
        r"([A-F][+-]?) Value\s*\|\s*([A-F][+-]?) Growth\s*\|\s*([A-F][+-]?) Momentum\s*\|\s*([A-F][+-]?) VGM",
        compact,
        flags=re.IGNORECASE,
    )
    if rank is None and not style_match and "Detailed Estimates" not in text:
        return []
    style_scores = None
    if style_match:
        style_scores = {
            "value": style_match.group(1).upper(),
            "growth": style_match.group(2).upper(),
            "momentum": style_match.group(3).upper(),
            "vgm": style_match.group(4).upper(),
        }
    industry = re.search(r"Zacks Industry Rank\s+More Info\s+(.+?)\s+Zacks Sector Rank", compact)
    sector = re.search(r"Zacks Sector Rank\s+More Info\s+(.+?)\s+Style Scores", compact)
    record = _record(
        ticker,
        "zacks",
        "detailed_estimates",
        rating=f"Rank #{rank}" if rank else "Detailed estimates",
        score=rank,
        extra={
            "zacks_rank": rank,
            "style_scores": style_scores,
            "industry_rank": industry.group(1).strip() if industry else None,
            "sector_rank": sector.group(1).strip() if sector else None,
            "earnings_esp_pct": _regex_float(compact, r"Earnings ESP\s+More Info\s+(-?[0-9.,]+)%"),
            "abr": _regex_float(compact, r"ABR\s+([0-9.,]+)"),
            "current_quarter_eps": _regex_float(compact, r"Current Quarter\s+(-?[0-9.,]+)"),
            "current_year_eps": _regex_float(compact, r"Current Year\s+(-?[0-9.,]+)"),
            "next_year_eps": _regex_float(compact, r"Next Year\s+(-?[0-9.,]+)"),
            "eps_ttm": _regex_float(compact, r"EPS \(TTM\)\s+(-?[0-9.,]+)"),
            "forward_pe": _regex_float(compact, r"P/E \(F1\)\s+(-?[0-9.,]+)"),
            "estimate_horizon_labels": _parse_zacks_horizon_labels(text),
            "sales_estimates": _parse_zacks_four_column_table(text, "Sales Estimates", "Earnings Estimates"),
            "earnings_estimates": _parse_zacks_four_column_table(
                text, "Earnings Estimates", "Agreement - Estimate Revisions"
            ),
            "revision_agreement": _parse_zacks_four_column_table(
                text, "Agreement - Estimate Revisions", "Magnitude - Consensus Estimate Trend"
            ),
            "consensus_trend": _parse_zacks_four_column_table(
                text,
                "Magnitude - Consensus Estimate Trend",
                "Upside - Most Accurate Estimate Versus Zacks Consensus",
            ),
            "earnings_surprise_history": _parse_zacks_surprise_history(text),
        },
    )
    return [record]


def parse_zacks_insider_transactions(ticker: str, text: str) -> list[dict[str, Any]]:
    transactions = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("EQUITY_INSIDER_TXN "):
            continue
        try:
            payload = json.loads(line.removeprefix("EQUITY_INSIDER_TXN "))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        name = str(payload.get("insider_name") or "").strip()
        code = str(payload.get("transaction_code") or "").strip().upper()
        date = str(payload.get("transaction_date") or "").strip()
        if not name or not re.fullmatch(r"[AD][ACDEFGHIJLMOPSUWXZ]", code) or not date:
            continue
        transactions.append(
            {
                "insider_name": name,
                "relationship": str(payload.get("relationship") or "").strip() or None,
                "transaction_date": date,
                "transaction_code": code,
                "direction": "acquired" if code.startswith("A") else "disposed",
                "classification": _classify_zacks_insider_code(code),
                "owner_type": str(payload.get("owner_type") or "").strip() or None,
                "security_type": str(payload.get("security_type") or "").strip() or None,
                "shares": _number(payload.get("shares")),
                "price": _number(payload.get("price")),
                "transaction_value": _number(payload.get("transaction_value")),
                "shares_owned_after": _number(payload.get("shares_owned_after")),
            }
        )
    if not transactions:
        structured = _structured_research_rows(text, "zacks", "insider_transactions")
        for row in structured:
            name = _structured_value(row, "filers name", "filer s name", "filer name", "insider name")
            code = str(_structured_value(row, "tran type", "transaction type") or "").upper()
            raw_date = _structured_value(row, "tran date", "transaction date")
            date = _date_iso(str(raw_date or ""), "%m/%d/%y") or _date_iso(str(raw_date or ""), "%m/%d/%Y")
            if not name or not re.fullmatch(r"[AD][ACDEFGHIJLMOPSUWXZ]", code) or not date:
                continue
            transactions.append({
                "insider_name": str(name),
                "relationship": _structured_value(row, "relationship title", "relationship"),
                "transaction_date": date,
                "transaction_code": code,
                "direction": "acquired" if code.startswith("A") else "disposed",
                "classification": _classify_zacks_insider_code(code),
                "owner_type": _structured_value(row, "owner type"),
                "security_type": _structured_value(row, "security type"),
                "shares": _number(_structured_value(row, "shares")),
                "price": _number(_structured_value(row, "price")),
                "transaction_value": _number(_structured_value(row, "tran value", "transaction value")),
                "shares_owned_after": _number(_structured_value(row, "total shares owned", "shares owned after")),
            })
        if not transactions:
            return []
    return [
        _record(
            ticker,
            "zacks",
            "insider_transactions",
            rating=f"{len(transactions)} recent transactions",
            score=len(transactions),
            extra={
                "transaction_count": len(transactions),
                "transactions": transactions,
                "verification_status": "requires_sec_form4_cross_check",
            },
        )
    ]


def parse_zacks_options(ticker: str, page_type: str, text: str) -> list[dict[str, Any]]:
    structured = _structured_research_rows(text, "zacks", page_type)
    if structured:
        return [_record(
            ticker,
            "zacks",
            page_type,
            rating=f"{len(structured)} visible table rows",
            score=len(structured),
            extra={"coverage": "visible_structured_table", "rows": structured},
        )]
    if page_type == "options_chain":
        rows = []
        pattern = re.compile(
            rf"(?m)^{re.escape(normalize_ticker(ticker))}\s+[A-Z][a-z]{{2}}\d{{2}}\s*\r?\n\t(\d{{2}}/\d{{2}}/\d{{4}})\t([^\r\n]+)$"
        )
        for match in pattern.finditer(str(text or "")):
            values = [value.strip() for value in match.group(2).split("\t")]
            if len(values) < 7:
                continue
            parsed = [_number_or_none(value) for value in values[:7]]
            rows.append({
                "contract_type": "call" if f"CALLS for {normalize_ticker(ticker)}" in text else "put",
                "expiration": _date_iso(match.group(1), "%m/%d/%Y"),
                "strike": parsed[0], "last": parsed[1], "open": parsed[2], "high": parsed[3],
                "low": parsed[4], "change": parsed[5], "volume": parsed[6],
            })
        if not rows:
            return []
        compact = _compact(text)
        return [_record(
            ticker, "zacks", "options_chain", rating=f"{len(rows)} option rows", score=len(rows),
            extra={
                "spot_price": _regex_float(compact, r"Last\s+\$([0-9.,]+)"),
                "coverage": "visible_selected_contract_type",
                "rows": rows,
            },
        )]
    if page_type != "greeks_montage":
        return []
    heading_pattern = re.compile(
        r"(?m)^[ \t]*([A-Z][a-z]{2}\s+\d{1,2})\s+(CALLS|PUTS)\s+/\s+(\d+)\s+Days to Expiration\s+\(([A-Z][a-z]{2}\s+\d{1,2}\s+\d{4})\)\s*$"
    )
    headings = list(heading_pattern.finditer(str(text or "")))
    rows = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        segment = text[heading.end():end]
        expiration = _date_iso(heading.group(4), "%b %d %Y")
        contract_type = "call" if heading.group(2) == "CALLS" else "put"
        for match in re.finditer(r"(?m)^[ \t]*([0-9]+(?:\.[0-9]+)?)[ \t]*\r?\n[ \t]+([^\r\n]+)$", segment):
            values = [value.strip() for value in match.group(2).strip().split("\t")]
            if len(values) < 15:
                continue
            parsed = [_number_or_none(value) for value in values[:15]]
            rows.append(
                {
                    "contract_type": contract_type,
                    "expiration": expiration,
                    "dte": int(heading.group(3)),
                    "strike": _number_or_none(match.group(1)),
                    "bid": parsed[0], "ask": parsed[1], "last": parsed[2], "change": parsed[3],
                    "high": parsed[4], "low": parsed[5], "volume": parsed[6], "open_interest": parsed[7],
                    "implied_volatility_pct": parsed[8], "theoretical_value": parsed[9],
                    "delta": parsed[10], "gamma": parsed[11], "theta": parsed[12],
                    "vega": parsed[13], "rho": parsed[14],
                }
            )
    if not rows:
        return []
    deduped_rows = []
    seen_contracts = set()
    for row in rows:
        key = (row.get("contract_type"), row.get("expiration"), row.get("strike"))
        if key in seen_contracts:
            continue
        seen_contracts.add(key)
        deduped_rows.append(row)
    rows = deduped_rows
    spot = _regex_float(_compact(text), r"Last\s+\$([0-9.,]+)")
    as_of_match = re.search(r"Updated\s+([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})", text)
    return [_record(
        ticker, "zacks", "greeks_montage", rating=f"{len(rows)} option rows", score=len(rows),
        extra={
            "spot_price": spot,
            "as_of": _date_iso(as_of_match.group(1), "%b %d, %Y") if as_of_match else None,
            "coverage": "visible_near_money_rows",
            "rows": rows,
        },
    )]


def parse_seeking_alpha_options(ticker: str, text: str) -> list[dict[str, Any]]:
    structured = _structured_research_rows(text, "seeking_alpha", "options_chain")
    if structured:
        return [_record(
            ticker,
            "seeking_alpha",
            "options_chain",
            rating=f"{len(structured)} visible table rows",
            score=len(structured),
            extra={"coverage": "visible_structured_table", "rows": structured},
        )]
    lines = _lines(text)
    rows = []
    for contract_label in ("Calls", "Puts"):
        starts = [i for i, line in enumerate(lines) if line == contract_label]
        if not starts:
            continue
        start = starts[-1]
        header_indexes = [i for i in range(start + 1, len(lines)) if lines[i].startswith("Strike\tPrice\tChange")]
        if not header_indexes:
            continue
        cursor = header_indexes[1] + 1 if len(header_indexes) > 1 else header_indexes[0] + 1
        end = next((i for i in range(cursor, len(lines)) if lines[i] in ({"Puts"} if contract_label == "Calls" else {"Options data delayed by 15 minutes"})), len(lines))
        while cursor + 8 < end:
            values = lines[cursor:cursor + 9]
            if _number_or_none(values[0]) is None or not re.search(r"\d{1,2}:\d{2}\s+[AP]M", values[8], re.I):
                cursor += 1
                continue
            rows.append({
                "contract_type": contract_label[:-1].lower(),
                "expiration": None,
                "dte": None,
                "strike": _number_or_none(values[0]), "last": _number_or_none(values[1]),
                "change": _number_or_none(values[2]), "change_pct": _number_or_none(values[3]),
                "bid": _number_or_none(values[4]), "ask": _number_or_none(values[5]),
                "volume": _number_or_none(values[6]), "open_interest": _number_or_none(values[7]),
                "last_trade_time": values[8],
            })
            cursor += 9
    if not rows:
        return []
    compact = _compact(text)
    spot = _regex_float(compact, rf"{re.escape(normalize_ticker(ticker))}\s+Summary.*?\$([0-9.,]+)")
    as_of_match = re.search(r"\d{1,2}:\d{2}\s+[AP]M\s+(\d{2}/\d{2}/\d{2})", text)
    return [_record(
        ticker, "seeking_alpha", "options_chain", rating=f"{len(rows)} option rows", score=len(rows),
        extra={
            "spot_price": spot,
            "as_of": _date_iso(as_of_match.group(1), "%m/%d/%y") if as_of_match else None,
            "coverage": "visible_selected_expiration",
            "rows": rows,
        },
    )]


def _parse_investing_options_chain(ticker: str, text: str) -> dict[str, Any] | None:
    structured = _structured_research_rows(text, "investing_pro", "options_chain")
    if structured:
        return _record(
            ticker,
            "investing_pro",
            "options_chain",
            rating=f"{len(structured)} visible table rows",
            score=len(structured),
            extra={"coverage": "visible_structured_table", "rows": structured},
        )
    compact = _compact(text)
    expiration_match = re.search(r"Expiration Date:\s+([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})", compact)
    expiration = _date_iso(expiration_match.group(1), "%b %d, %Y") if expiration_match else None
    rows = []
    for raw_line in str(text or "").splitlines():
        values = [value.strip() for value in raw_line.strip().split("\t")]
        if len(values) != 11 or _number_or_none(values[5]) is None:
            continue
        call_values = [_number_or_none(value) for value in values[:5]]
        put_values = [_number_or_none(value) for value in values[6:]]
        strike = _number_or_none(values[5])
        rows.extend([
            {"contract_type": "call", "expiration": expiration, "strike": strike, "last": call_values[0], "change_pct": call_values[1], "bid": call_values[2], "ask": call_values[3], "volume": call_values[4]},
            {"contract_type": "put", "expiration": expiration, "strike": strike, "last": put_values[0], "change_pct": put_values[1], "bid": put_values[2], "ask": put_values[3], "volume": put_values[4]},
        ])
    if not rows:
        return None
    as_of_match = re.search(r"Price @\s+([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})", text)
    price_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*\r?\n\s*Price @", text)
    return _record(
        ticker, "investing_pro", "options_chain", rating=f"{len(rows)} option rows", score=len(rows),
        extra={
            "spot_price": _number_or_none(price_match.group(1)) if price_match else None,
            "as_of": _date_iso(as_of_match.group(1), "%b %d, %Y") if as_of_match else None,
            "coverage": "visible_selected_expiration_quotes",
            "rows": rows,
        },
    )


def _structured_research_rows(text: str, provider: str, data_type: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("EQUITY_RESEARCH_TABLE "):
            continue
        try:
            payload = json.loads(line.removeprefix("EQUITY_RESEARCH_TABLE "))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if payload.get("provider") != provider or payload.get("data_type") != data_type:
            continue
        headers = [str(value or "").strip() for value in payload.get("headers") or []]
        for raw_row in payload.get("rows") or []:
            values = [str(value or "").strip() for value in raw_row or []]
            if len(values) < 3:
                continue
            names = headers if len(headers) == len(values) else [f"column_{index + 1}" for index in range(len(values))]
            if all(name.lower() == value.lower() for name, value in zip(names, values)):
                continue
            rows.append(dict(zip(names, values)))
    return rows


def _structured_value(row: dict[str, Any], *aliases: str) -> Any:
    normalized_aliases = {re.sub(r"[^a-z0-9]+", " ", alias.lower()).strip() for alias in aliases}
    for key, value in row.items():
        normalized_key = re.sub(r"[^a-z0-9]+", " ", str(key).lower()).strip()
        if normalized_key in normalized_aliases:
            return value
    return None


def _number_or_none(raw: Any) -> float | None:
    value = str(raw if raw is not None else "").strip().replace("$", "").replace(",", "").replace("%", "")
    if value.upper() in {"", "-", "NA", "N/A"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _date_iso(raw: str, fmt: str) -> str | None:
    try:
        return datetime.strptime(str(raw).strip(), fmt).date().isoformat()
    except ValueError:
        return None


def _classify_zacks_insider_code(code: str) -> str:
    return {
        "AP": "open_market_purchase",
        "DS": "open_market_sale",
        "AA": "grant_or_award",
        "AM": "option_exercise_or_conversion",
        "AO": "option_exercise_or_conversion",
        "AX": "option_exercise_or_conversion",
        "DF": "tax_or_exercise_withholding",
        "AF": "tax_or_exercise_withholding",
        "AG": "gift",
        "DG": "gift",
        "DD": "issuer_disposition",
    }.get(code, "other_non_open_market")


def _number(raw: Any) -> float | None:
    value = str(raw if raw is not None else "").strip().replace("$", "").replace(",", "")
    if value in {"", "-", "N/A", "NA"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_sa_factor_page(ticker: str, category: str, text: str) -> dict[str, Any] | None:
    lines = _lines(text)
    grade_label = f"{normalize_ticker(ticker)} {category.title()} Grade"
    try:
        grade_index = next(i for i, line in enumerate(lines) if line.lower() == grade_label.lower())
    except StopIteration:
        return None
    grade = next((line.upper() for line in lines[grade_index + 1 : grade_index + 5] if GRADE_PATTERN.match(line)), None)
    table_header = next(
        (
            i
            for i in range(grade_index, len(lines))
            if "Sector Relative Grade" in lines[i]
            or (
                lines[i].startswith("Type\tGrade\t")
                and "Sector Median" in lines[i]
                and "% Diff. to Sector" in lines[i]
            )
        ),
        None,
    )
    if table_header is None:
        return None
    start = table_header + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("*Grades are relative")), len(lines))
    metrics = []
    index = start
    while index + 6 < end:
        name = lines[index]
        metric_grade = lines[index + 1].upper()
        if not GRADE_PATTERN.match(metric_grade):
            index += 1
            continue
        values = lines[index + 2 : index + 7]
        metrics.append(
            {
                "metric": name,
                "grade": metric_grade,
                "grade_score": GRADE_SCORE.get(metric_grade),
                "company": _value(values[0]),
                "sector_median": _value(values[1]),
                "difference_to_sector": _value(values[2]),
                "five_year_average": _value(values[3]),
                "difference_to_five_year_average": _value(values[4]),
            }
        )
        index += 7
    if not metrics:
        metrics = _parse_sa_ungraded_factor_metrics(lines, start, end)
    if not metrics:
        return None
    return _record(
        ticker,
        "seeking_alpha",
        f"{category}_metrics",
        rating=grade or f"{category.title()} metrics",
        score=GRADE_SCORE.get(grade or ""),
        extra={"category": category, "grade": grade, "metrics": metrics},
    )


def _parse_sa_ungraded_factor_metrics(
    lines: list[str],
    start: int,
    end: int,
) -> list[dict[str, Any]]:
    metrics = []
    seen = set()
    for marker_index in range(start, end):
        marker = lines[marker_index].strip().upper()
        if not marker.startswith("RATING:"):
            continue
        metric_index = marker_index - 1
        while metric_index >= start and (
            lines[metric_index].strip() in {"", "-"}
            or GRADE_PATTERN.match(lines[metric_index].strip().upper())
        ):
            metric_index -= 1
        if metric_index < start:
            continue
        metric_name = lines[metric_index].strip()
        if metric_name in seen or metric_name.startswith("RATING:"):
            continue
        values = []
        cursor = marker_index + 1
        while cursor < end and len(values) < 5:
            raw = lines[cursor].strip()
            parsed = _value(raw)
            if parsed.get("unit") == "text" and raw.upper() not in {"NM", "NA", "N/A"}:
                break
            values.append(parsed)
            cursor += 1
        if len(values) != 5 or not any(item.get("value") is not None for item in values):
            continue
        grade_match = re.fullmatch(r"RATING:\s*([A-F](?:[+-])?)", marker, flags=re.IGNORECASE)
        metric_grade = grade_match.group(1).upper() if grade_match else None
        metrics.append(
            {
                "metric": metric_name,
                "grade": metric_grade,
                "grade_score": GRADE_SCORE.get(metric_grade or ""),
                "company": values[0],
                "sector_median": values[1],
                "difference_to_sector": values[2],
                "five_year_average": values[3],
                "difference_to_five_year_average": values[4],
            }
        )
        seen.add(metric_name)
    return metrics


def _parse_sa_statement(ticker: str, page_type: str, text: str) -> dict[str, Any] | None:
    raw_lines = [line.rstrip() for line in str(text or "").splitlines()]
    header = next(
        (
            line
            for line in raw_lines
            if "\tTTM\t" in line
            and re.search(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) 20", line)
        ),
        None,
    )
    periods: list[str] = []
    rows: list[dict[str, Any]] = []
    if header:
        header_cells = [cell.strip() for cell in header.split("\t") if cell.strip()]
        ttm_index = next((index for index, cell in enumerate(header_cells) if cell.upper() == "TTM"), 0)
        periods = header_cells[ttm_index:]
        seen_rows: set[tuple[str, tuple[str, ...]]] = set()
        for line in raw_lines:
            cells = [cell.strip() for cell in line.split("\t") if cell.strip()]
            if len(cells) != len(periods) + 1:
                continue
            parsed_values = [_value(cell) for cell in cells[1:]]
            if not any(item.get("value") is not None for item in parsed_values):
                continue
            row_key = (cells[0], tuple(cell["raw"] for cell in parsed_values))
            if row_key in seen_rows:
                continue
            seen_rows.add(row_key)
            rows.append({"metric": cells[0], "values": dict(zip(periods, parsed_values))})
    if not rows:
        periods, rows = _parse_sa_statement_lines(raw_lines)
    if not rows:
        return None
    currency_match = re.search(r"In Millions of ([^(\n]+)", text)
    if not currency_match:
        currency_match = re.search(r"attributes\.(?:companyPrimaryCurrency|currency)\s*=\s*([A-Z]{3})", text)
    return _record(
        ticker,
        "seeking_alpha",
        page_type,
        rating=page_type.replace("_", " ").title(),
        extra={
            "periods": periods,
            "rows": rows,
            "statement_scale": 1_000_000,
            "statement_currency_label": currency_match.group(1).strip() if currency_match else None,
        },
    )


def _parse_sa_statement_lines(raw_lines: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
    lines = [line.strip() for line in raw_lines if line.strip()]
    period_pattern = re.compile(
        r"^(?:TTM|FY\s*20[0-9]{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(?:\s+[0-9]{1,2},)?\s+20[0-9]{2}|20[0-9]{2})$",
        flags=re.IGNORECASE,
    )
    start = None
    periods: list[str] = []
    for index in range(len(lines)):
        candidate = []
        for line in lines[index : index + 12]:
            if period_pattern.match(line):
                candidate.append(line)
            elif candidate:
                break
        if len(candidate) >= 2:
            start = index + len(candidate)
            periods = candidate
            break
    if start is None:
        return [], []
    rows = []
    index = start
    while index < len(lines):
        metric = lines[index]
        if period_pattern.match(metric) or _value(metric).get("value") is not None:
            index += 1
            continue
        values = []
        cursor = index + 1
        while cursor < len(lines) and len(values) < len(periods):
            parsed = _value(lines[cursor])
            if parsed.get("value") is None and parsed.get("unit") == "text":
                break
            values.append(parsed)
            cursor += 1
        if len(values) == len(periods) and any(item.get("value") is not None for item in values):
            rows.append({"metric": metric, "values": dict(zip(periods, values))})
            index = cursor
        else:
            index += 1
    return periods, rows


def _parse_sa_peers(ticker: str, text: str) -> dict[str, Any] | None:
    raw_lines = [line.rstrip() for line in str(text or "").splitlines()]
    symbol_line = next((line for line in raw_lines if re.match(r"^\s*\t?[A-Z0-9.:-]+(?:\t[A-Z0-9.:-]+){2,}", line)), None)
    if symbol_line:
        symbols = [cell.strip().upper() for cell in symbol_line.split("\t") if cell.strip()]
    else:
        chart_symbols = re.search(
            r"^[ \t]*([A-Z0-9.:-]+(?:,\s*[A-Z0-9.:-]+)+(?:\s+and\s+[A-Z0-9.:-]+)?)[ \t]*$\n[ \t]*Line chart with",
            text,
            flags=re.MULTILINE,
        )
        if not chart_symbols:
            return None
        symbols = re.findall(r"[A-Z][A-Z0-9.:-]*", chart_symbols.group(1))
    metrics: dict[str, dict[str, Any]] = {}
    for label in ["Company Name", "Market Cap", "Enterprise Value", "SA Analysts Covering", "Wall St. Analysts"]:
        values = _tabular_values_after_label(raw_lines, label, len(symbols))
        if values:
            metrics[label] = dict(zip(symbols, [_value(value) for value in values]))
    if "Price Return" not in metrics:
        returns = {
            match.group(1): _value(match.group(2) + "%")
            for match in re.finditer(
                r"^[ \t]*([A-Z][A-Z0-9.:-]*)[ \t]*$\n[ \t]*(-?[0-9.,]+)%[ \t]*$\n[ \t]*Price Return[ \t]*$",
                text,
                flags=re.MULTILINE,
            )
            if match.group(1) in symbols
        }
        if returns:
            metrics["Price Return"] = returns
    factor_grades = {}
    for label in ["Valuation", "Growth", "Profitability", "Momentum", "EPS Revisions"]:
        values = _sequential_values_after_label(raw_lines, label, len(symbols), GRADE_PATTERN)
        if values:
            factor_grades[label.lower().replace(" ", "_")] = dict(zip(symbols, values))
    ranks = {}
    for label in ["Sector Rank", "Industry Rank"]:
        line = next((line for line in raw_lines if line.strip().startswith(label + "\t")), None)
        if line:
            values = [cell.strip() for cell in line.split("\t")[1:] if cell.strip()]
            ranks[label.lower().replace(" ", "_")] = dict(zip(symbols, values[: len(symbols)]))
    return _record(
        ticker,
        "seeking_alpha",
        "peer_comparison",
        rating="Peer comparison",
        extra={"peer_symbols": symbols, "profile_metrics": metrics, "factor_grades": factor_grades, "ranks": ranks},
    )


def _parse_sa_estimates(ticker: str, text: str) -> dict[str, Any] | None:
    compact = _compact(text)
    structured_rows = _parse_sa_structured_estimates(text)
    if "annual estimates summary" not in compact.casefold() and not structured_rows:
        return None
    table_eps_rows = _regex_estimate_rows(
        compact,
        "Fiscal Period Ending EPS Estimate YoY Growth Forward PE Low High # of Analysts",
        ["Consensus Revenue Estimates"],
        revenue=False,
    )
    table_revenue_rows = _regex_estimate_rows(
        compact,
        "Fiscal Period Ending Revenue Estimate YoY Growth FWD Price/Sales Low High # of Analysts",
        [
            "EPS estimates are GAAP unless otherwise noted",
            "EPS estimates are Normalized",
            "Seeking Alpha - Power to Investors",
        ],
        revenue=True,
    )
    eps_rows = _merge_sa_estimate_rows(table_eps_rows, structured_rows, "eps")
    revenue_rows = _merge_sa_estimate_rows(table_revenue_rows, structured_rows, "revenue")
    return _record(
        ticker,
        "seeking_alpha",
        "estimates",
        rating="Annual estimates",
        extra={
            "eps_estimates": eps_rows,
            "revenue_estimates": revenue_rows,
            "extraction_method": (
                "ssr_data_with_visible_table_enrichment" if structured_rows and (table_eps_rows or table_revenue_rows)
                else "ssr_data" if structured_rows
                else "visible_table"
            ),
        },
    )


def _parse_sa_revisions(ticker: str, text: str) -> dict[str, Any] | None:
    compact = _compact(text)
    structured_counts = _parse_sa_structured_revision_counts(text)
    if "annual estimates revisions" not in compact.casefold() and not structured_counts:
        return None
    visible_counts = {
        "eps_up": _regex_int(compact, r"EPS # of Up Revisions\s+([0-9]+)"),
        "eps_down": _regex_int(compact, r"EPS # of Down Revisions\s+([0-9]+)"),
        "revenue_up": _regex_int(compact, r"Revenue # of Up Revisions\s+([0-9]+)"),
        "revenue_down": _regex_int(compact, r"Revenue # of Down Revisions\s+([0-9]+)"),
    }
    counts = {
        key: structured_counts.get(key) if structured_counts.get(key) is not None else value
        for key, value in visible_counts.items()
    }
    eps_trend = _regex_revision_rows(
        compact,
        "Fiscal Period Ending EPS Estimate YoY Growth 1M Trend 3M Trend 6M Trend",
        ["Consensus Revenue Revision Trend"],
        revenue=False,
    )
    revenue_trend = _regex_revision_rows(
        compact,
        "Fiscal Period Ending Revenue Estimate YoY Growth 1M Trend 3M Trend 6M Trend",
        ["Seeking Alpha - Power to Investors"],
        revenue=True,
    )
    return _record(
        ticker,
        "seeking_alpha",
        "revisions",
        rating="Estimate revisions",
        score=(counts["eps_up"] or 0) + (counts["revenue_up"] or 0) - (counts["eps_down"] or 0) - (counts["revenue_down"] or 0),
        extra={
            "revision_counts_3m": counts,
            "eps_revision_trend": eps_trend,
            "revenue_revision_trend": revenue_trend,
            "structured_revision_snapshot": structured_counts or None,
            "extraction_method": (
                "ssr_data_with_visible_table_enrichment" if structured_counts and (eps_trend or revenue_trend)
                else "ssr_data" if structured_counts
                else "visible_table"
            ),
        },
    )


def _parse_investing_overview(ticker: str, text: str) -> dict[str, Any] | None:
    lines = _lines(text)
    if "Key Statistics" not in lines:
        return None
    key_labels = [
        "Prev. Close", "Market Cap", "Shares Outstanding", "Revenue", "Net Income", "EPS",
        "EPS Growth Forecast", "Gross Profit Margin", "P/E Ratio", "Return on Assets",
        "Return on Equity", "Price/Book", "EBITDA", "EV/EBITDA", "Beta",
        "Book Value / Share", "Relative Strength Index (14d)",
    ]
    metrics = {label: _value(_line_after(lines, label)) for label in key_labels if _line_after(lines, label)}
    financial_health = _first_line_after(lines, ["Company's Health", "Company’s Health"])
    return _record(
        ticker,
        "investing_pro",
        "overview",
        rating=financial_health or "Overview",
        extra={
            "financial_health": financial_health,
            "fair_value_label": _line_after(lines, "Fair Value"),
            "fair_value": _value(_line_after(lines, "Fair Price")),
            "fair_value_upside": _value(_line_after(lines, "Upside")),
            "analyst_sentiment": _line_after(lines, "Analysts Sentiment"),
            "analyst_price_target": _value(_line_after(lines, "Price Target")),
            "metrics": metrics,
        },
    )


def _parse_investing_financial_summary(ticker: str, text: str) -> dict[str, Any] | None:
    lines = _lines(text)
    if "Statements Highlights" not in lines:
        return None
    years = []
    start = lines.index("Statements Highlights")
    for line in lines[start : start + 40]:
        if re.fullmatch(r"20[0-9]{2}", line):
            years.append(line)
    metrics = {}
    for label in [
        "Total Revenues", "Gross Profit", "Operating Income", "Net Income", "Total Assets",
        "Total Current Liabilities", "Total Equity", "Levered Free Cash Flow", "Cash from Operations",
        "Cash from Investing", "Cash from Financing", "Net Change in Cash",
    ]:
        raw_values = _numeric_line_after(lines, label)
        if raw_values:
            metrics[label] = dict(zip(years, [_value(value) for value in raw_values]))
    return _record(
        ticker,
        "investing_pro",
        "financial_summary",
        rating="Financial summary",
        extra={"periods": years, "statement_scale": 1_000_000, "metrics": metrics},
    )


def _parse_investing_cash_flow(ticker: str, text: str) -> dict[str, Any] | None:
    lines = _lines(text)
    if not any("Cash Flow Statement" in line for line in lines):
        return None
    periods = [line for line in lines if re.fullmatch(r"20[0-9]{2}", line)][:10]
    metrics = {}
    for label in [
        "Cash from Operations", "Capital Expenditure", "Cash from Investing", "Cash from Financing",
        "Repurchase of Common Stock", "Common & Preferred Stock Dividends Paid", "Net Change in Cash",
    ]:
        raw_values = _numeric_line_after(lines, label)
        if raw_values:
            metrics[label] = dict(zip(periods, [_value(value) for value in raw_values]))
    return _record(
        ticker,
        "investing_pro",
        "cash_flow_statement",
        rating="Cash flow statement",
        extra={"periods": periods, "statement_scale": 1_000_000, "metrics": metrics},
    )


def _parse_investing_ratios(ticker: str, text: str) -> dict[str, Any] | None:
    lines = _lines(text)
    categories = [
        "Valuation Ratios", "Profitability", "Per Share Data", "Management Effectiveness",
        "Growth", "Financial Strength", "Efficiency", "DIVIDEND",
    ]
    if "Valuation Ratios" not in lines:
        return None
    result = {}
    for category_index, category in enumerate(categories):
        if category not in lines:
            continue
        start = lines.index(category) + 1
        later = [lines.index(other) for other in categories[category_index + 1 :] if other in lines]
        end = min(later) if later else len(lines)
        segment = lines[start:end]
        labels = [line for line in segment if _looks_like_ratio_label(line)]
        pairs = [line for line in segment if _split_numeric_cells(line, expected=2)]
        result[category.lower().replace(" ", "_")] = [
            {
                "metric": label,
                "company": _value(pair[0]),
                "industry": _value(pair[1]),
            }
            for label, pair in zip(labels, (_split_numeric_cells(line, expected=2) for line in pairs))
            if pair
        ]
    return _record(
        ticker,
        "investing_pro",
        "ratios",
        rating="Company vs industry ratios",
        extra={"categories": result},
    )


def _parse_investing_forecast(ticker: str, text: str) -> dict[str, Any] | None:
    compact = _compact(text)
    if "Advanced Equity Forecast" not in compact:
        return None
    model_matches = re.findall(
        r"(P/E Multiples|Dividends: Stable Growth|Dividends: Multi-Stage|Earnings Power Value|EBITDA Multiples|Revenue Multiples|Multiples Valuation: Price / Sales|Multiples Valuation: Price / Book|Multiples Valuation: EBIT|10Y DCF Revenue Exit|10Y DCF EBITDA Exit|5Y DCF Revenue Exit|5Y DCF EBITDA Exit|5Y DCF Terminal Growth Exit|10Y DCF Terminal Growth Exit)\s+\$?([0-9.,]+)",
        compact,
    )
    return _record(
        ticker,
        "investing_pro",
        "forecast",
        rating=_regex_text(compact, r"Overall Consensus\s+(Strong Buy|Buy|Hold|Sell|Strong Sell)") or "Forecast",
        extra={
            "rating_count": _regex_int(compact, r"([0-9]+)\s*Ratings"),
            "buy_count": _regex_int(compact, r"([0-9]+) Buy"),
            "hold_count": _regex_int(compact, r"([0-9]+) Hold"),
            "sell_count": _regex_int(compact, r"([0-9]+) Sell"),
            "analyst_target_average": _regex_float(compact, r"Analysts 12-Month Price Target\s+Average\s+([0-9.,]+)"),
            "analyst_target_low": _regex_float(compact, r"Past 24 Months.*?Low\s+([0-9.,]+)"),
            "analyst_target_high": _regex_float(compact, r"Past 24 Months.*?High\s+([0-9.,]+)"),
            "fair_value": _regex_float(compact, r"Fair Value\s+Average\s+([0-9.,]+)"),
            "fair_value_uncertainty": _regex_text(compact, r"Uncertainty\s+([A-Z]+)"),
            "fair_value_upside_pct": _signed_fair_value_upside(compact),
            "fair_value_model_count": _regex_int(compact, r"Fair Value\s+([0-9]+) models"),
            "valuation_models": {name: float(value.replace(",", "")) for name, value in model_matches},
        },
    )


def _parse_investing_ownership(ticker: str, text: str) -> dict[str, Any] | None:
    lines = _lines(text)
    if "Ownership Overview" not in lines:
        return None
    composition = []
    for label in ["Mutual Funds & ETFs", "Other Institutional Investors", "Public Companies & Retail Investors", "Total"]:
        values = _split_numeric_cells(_line_after(lines, label), expected=3)
        if values:
            composition.append(
                {
                    "holder_type": label,
                    "shares": _value(values[0]),
                    "percent_outstanding": _value(values[1]),
                    "market_value": _value(values[2]),
                }
            )
    return _record(
        ticker,
        "investing_pro",
        "ownership",
        rating="Ownership",
        extra={"composition": composition},
    )


def _parse_zacks_four_column_table(text: str, start_label: str, end_label: str) -> dict[str, Any]:
    compact = _compact(text)
    folded = compact.casefold()
    end = folded.find(end_label.casefold())
    section = re.search(
        rf"{re.escape(start_label)}\s+Current Qtr\s*\(",
        compact,
        flags=re.IGNORECASE,
    )
    if section:
        start = section.start()
    else:
        candidates = [
            match.start()
            for match in re.finditer(re.escape(start_label), compact, flags=re.IGNORECASE)
            if end < 0 or match.start() < end
        ]
        start = candidates[-1] if candidates else -1
    end = folded.find(end_label.casefold(), start + len(start_label))
    if start < 0:
        return {}
    segment = compact[start : end if end >= 0 else len(compact)]
    rows = {}
    labels = [
        "Zacks Consensus Estimate", "# of Estimates", "Most Recent Consensus", "High Estimate",
        "Low Estimate", "Year ago Sales", "Year ago EPS", "Year over Year Growth Est.",
        "Up Last 7 Days", "Up Last 30 Days", "Up Last 60 Days", "Down Last 7 Days",
        "Down Last 30 Days", "Down Last 60 Days", "Current", "7 Days Ago", "30 Days Ago",
        "60 Days Ago", "90 Days Ago",
    ]
    token = r"(?:\$?[-+]?[0-9][0-9.,]*[KMBT]?%?|NA)"
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s+({token}(?:\s+{token}){{3}})", segment, flags=re.IGNORECASE)
        if not match:
            continue
        values = match.group(1).split()
        rows[label] = dict(zip(HORIZONS, [_value(value) for value in values]))
    return rows


def _parse_zacks_horizon_labels(text: str) -> dict[str, str]:
    compact = _compact(text)
    match = re.search(
        r"Sales Estimates\s+Current Qtr\s*\(([^)]+)\)\s+Next Qtr\s*\(([^)]+)\)\s+"
        r"Current Year\s*\(([^)]+)\)\s+Next Year\s*\(([^)]+)\)",
        compact,
        flags=re.IGNORECASE,
    )
    if not match:
        return {}
    return dict(zip(HORIZONS, [value.strip() for value in match.groups()]))


def _parse_zacks_surprise_history(text: str) -> dict[str, Any]:
    compact = _compact(text)
    match = re.search(r"Surprise\s+((?:[-+0-9.,]+%?\s+){{4}}[-+0-9.,]+%?)", compact)
    if not match:
        return {}
    values = match.group(1).split()
    return {"quarter_surprises": [_value(value) for value in values[:4]], "average_surprise": _value(values[4])}


def _casefold_segment(compact: str, start_label: str, end_labels: list[str]) -> str:
    folded = compact.casefold()
    start = folded.find(start_label.casefold())
    if start < 0:
        return ""
    ends = [
        folded.find(label.casefold(), start + len(start_label))
        for label in end_labels
    ]
    valid_ends = [end for end in ends if end >= 0]
    end = min(valid_ends) if valid_ends else len(compact)
    return compact[start:end]


def _regex_estimate_rows(
    compact: str,
    start_label: str,
    end_labels: list[str],
    revenue: bool,
) -> list[dict[str, Any]]:
    segment = _casefold_segment(compact, start_label, end_labels)
    if not segment:
        return []
    value_pattern = r"\$?[0-9]+(?:\.[0-9]+)?[BMT]?"
    pattern = re.compile(
        rf"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) 20[0-9]{{2}})\s+({value_pattern})\s+(-?[0-9.]+)%\s+([0-9.]+)\s+({value_pattern})\s+({value_pattern})\s+([0-9]+)",
        flags=re.IGNORECASE,
    )
    return [
        {
            "period": match.group(1),
            "estimate": _value(match.group(2)),
            "yoy_growth": _value(match.group(3) + "%"),
            "forward_multiple": _value(match.group(4)),
            "low": _value(match.group(5)),
            "high": _value(match.group(6)),
            "analyst_count": int(match.group(7)),
            "estimate_type": "revenue" if revenue else "eps",
        }
        for match in pattern.finditer(segment)
    ]


def _regex_revision_rows(
    compact: str,
    start_label: str,
    end_labels: list[str],
    revenue: bool,
) -> list[dict[str, Any]]:
    segment = _casefold_segment(compact, start_label, end_labels)
    if not segment:
        return []
    value_pattern = r"\$?-?[0-9]+(?:\.[0-9]+)?[BMT]?"
    pattern = re.compile(
        rf"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) 20[0-9]{{2}})\s+({value_pattern})\s+(-?[0-9.]+)%\s+(-?[0-9.]+)%\s+(-?[0-9.]+)%\s+(-?[0-9.]+)%",
        flags=re.IGNORECASE,
    )
    return [
        {
            "period": match.group(1),
            "estimate": _value(match.group(2)),
            "yoy_growth": _value(match.group(3) + "%"),
            "trend_1m": _value(match.group(4) + "%"),
            "trend_3m": _value(match.group(5) + "%"),
            "trend_6m": _value(match.group(6) + "%"),
            "estimate_type": "revenue" if revenue else "eps",
        }
        for match in pattern.finditer(segment)
    ]


def _parse_sa_structured_estimates(text: str) -> list[dict[str, Any]]:
    pattern = re.compile(
        r"^[ \t]*SA_DATA SSR_DATA\.estimatesSummary\[\d+\]\.estimates\.\d+\."
        r"(?P<metric>revenue_consensus_mean|eps_(?:gaap|normalized)_consensus_mean)\.\d+\[\d+\]\."
        r"(?P<field>dataitemvalue|effectivedate|period\.(?:fiscalyear|periodtypeid|periodenddate)) = (?P<value>.*)$",
        flags=re.MULTILINE | re.IGNORECASE,
    )
    grouped: dict[str, dict[str, str]] = {}
    for match in pattern.finditer(str(text or "")):
        metric = match.group("metric").lower()
        grouped.setdefault(metric, {})[match.group("field").lower()] = match.group("value").strip()
    rows = []
    for metric, fields in grouped.items():
        if fields.get("period.periodtypeid", "").lower() != "annual":
            continue
        year = fields.get("period.fiscalyear")
        raw_estimate = fields.get("dataitemvalue")
        if not year or raw_estimate is None:
            continue
        period_end = fields.get("period.periodenddate", "")
        month = "Dec"
        if re.match(r"\d{4}-\d{2}-\d{2}", period_end):
            month_number = int(period_end[5:7])
            month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][month_number - 1]
        rows.append({
            "period": f"{month} {year}",
            "estimate": _value(raw_estimate),
            "estimate_type": "revenue" if metric.startswith("revenue") else "eps",
            "estimate_basis": "gaap" if "gaap" in metric else "normalized" if "normalized" in metric else None,
            "effective_date": fields.get("effectivedate"),
            "structured_source": "SSR_DATA.estimatesSummary",
        })
    return rows


def _merge_sa_estimate_rows(
    table_rows: list[dict[str, Any]],
    structured_rows: list[dict[str, Any]],
    estimate_type: str,
) -> list[dict[str, Any]]:
    merged = {row["period"]: dict(row) for row in table_rows}
    for structured in (row for row in structured_rows if row.get("estimate_type") == estimate_type):
        period = structured["period"]
        if period in merged:
            merged[period]["display_estimate"] = merged[period]["estimate"]
            merged[period].update(structured)
            merged[period]["extraction_method"] = "ssr_data_with_visible_table_enrichment"
        else:
            merged[period] = {**structured, "extraction_method": "ssr_data"}
    return sorted(merged.values(), key=lambda row: row.get("period", "")[-4:])


def _parse_sa_structured_revision_counts(text: str) -> dict[str, int]:
    pattern = re.compile(
        r"^[ \t]*SA_DATA SSR_DATA\.revisions\.revisions\.\d+\."
        r"(?P<metric>revenue_consensus_mean|eps_(?:gaap|normalized)_consensus_mean)\.\d+\[\d+\]\."
        r"(?P<field>numanalystsup|numanalystsdown|numanalystsnochange|numanalysts) = (?P<value>\d+)$",
        flags=re.MULTILINE | re.IGNORECASE,
    )
    result: dict[str, int] = {}
    for match in pattern.finditer(str(text or "")):
        prefix = "revenue" if match.group("metric").lower().startswith("revenue") else "eps"
        field = match.group("field").lower()
        suffix = {
            "numanalystsup": "up",
            "numanalystsdown": "down",
            "numanalystsnochange": "no_change",
            "numanalysts": "analyst_count",
        }[field]
        result[f"{prefix}_{suffix}"] = int(match.group("value"))
    return result


def _record(
    ticker: str,
    provider: str,
    data_type: str,
    rating: str,
    score: float | int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "ticker": normalize_ticker(ticker),
        "provider": provider,
        "rating_type": data_type,
        "rating": rating,
        "score": score,
        "price_target": None,
        "currency": "USD",
        "source_text": rating,
    }
    if extra:
        record.update({key: value for key, value in extra.items() if value is not None})
    return record


def _lines(text: str) -> list[str]:
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def _compact(text: str) -> str:
    return " ".join(str(text or "").replace("\u2212", "-").split())


def _value(raw: str | None) -> dict[str, Any]:
    raw_value = str(raw or "").strip()
    normalized = raw_value.replace("$", "").replace(",", "").replace("\u2212", "-")
    if normalized in {"", "-", "NA", "NM", "N/A"}:
        return {"raw": raw_value, "value": None, "unit": None}
    negative_parentheses = normalized.startswith("(") and normalized.endswith(")")
    if negative_parentheses:
        normalized = "-" + normalized[1:-1]
    unit = None
    multiplier = 1.0
    if normalized.endswith("%"):
        unit = "percent"
        normalized = normalized[:-1]
    elif normalized.lower().endswith("x"):
        unit = "multiple"
        normalized = normalized[:-1]
    elif normalized[-1:].upper() in {"K", "M", "B", "T"}:
        suffix = normalized[-1].upper()
        multiplier = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[suffix]
        unit = "currency_or_count"
        normalized = normalized[:-1]
    try:
        value = float(normalized) * multiplier
    except ValueError:
        value = None
        unit = "text"
    return {"raw": raw_value, "value": value, "unit": unit}


def _line_after(lines: list[str], label: str) -> str | None:
    try:
        index = lines.index(label)
    except ValueError:
        return None
    return lines[index + 1] if index + 1 < len(lines) else None


def _first_line_after(lines: list[str], labels: list[str]) -> str | None:
    for label in labels:
        value = _line_after(lines, label)
        if value is not None:
            return value
    return None


def _numeric_line_after(lines: list[str], label: str) -> list[str]:
    try:
        index = lines.index(label)
    except ValueError:
        return []
    for line in lines[index + 1 : index + 5]:
        cells = _split_numeric_cells(line)
        if cells:
            return cells
    return []


def _split_numeric_cells(line: str | None, expected: int | None = None) -> list[str]:
    cells = [cell.strip() for cell in str(line or "").split("\t") if cell.strip()]
    if expected is not None and len(cells) != expected:
        return []
    if not cells or not all(_value(cell)["value"] is not None for cell in cells):
        return []
    return cells


def _looks_like_ratio_label(line: str) -> bool:
    if "\t" in line or _split_numeric_cells(line):
        return False
    return len(line) > 2 and line not in {"Collapse All", "Name", "Company", "Industry"}


def _tabular_values_after_label(lines: list[str], label: str, count: int) -> list[str]:
    line = next((line for line in lines if line.strip().startswith(label + "\t")), None)
    if not line:
        return []
    return [cell.strip() for cell in line.split("\t")[1:] if cell.strip()][:count]


def _sequential_values_after_label(
    lines: list[str], label: str, count: int, pattern: re.Pattern[str]
) -> list[str]:
    try:
        index = next(i for i, line in enumerate(lines) if line.strip() == label)
    except StopIteration:
        return []
    values = []
    for line in lines[index + 1 : index + 1 + count * 3]:
        value = line.strip().upper()
        if pattern.match(value):
            values.append(value)
            if len(values) == count:
                break
    return values


def _regex_float(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return float(match.group(1).replace(",", "").replace("\u2212", "-"))


def _signed_fair_value_upside(text: str) -> float | None:
    match = re.search(
        r"Fair Value\s+Average\s+[0-9.,]+\s+(Upside|Downside)\s+([+−-]?[0-9.,]+)%",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    value = float(match.group(2).replace(",", "").replace("\u2212", "-"))
    return -abs(value) if match.group(1).lower() == "downside" else value


def _regex_int(text: str, pattern: str) -> int | None:
    value = _regex_float(text, pattern)
    return int(value) if value is not None else None


def _regex_text(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None
