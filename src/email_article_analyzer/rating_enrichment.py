from pathlib import Path
import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from email_article_analyzer.article_content import ArticleContentFetcherProtocol
from email_article_analyzer.investing_mapping import InvestingInstrumentMapper
from email_article_analyzer.investing_mapping import load_investing_urls
from email_article_analyzer.repositories import RunRepository
from email_article_analyzer.research_metrics import (
    parse_investing_research,
    parse_seeking_alpha_research,
    parse_seeking_alpha_options,
    parse_zacks_detailed_estimates,
    parse_zacks_insider_transactions,
    parse_zacks_options,
)
from email_article_analyzer.watchlist import normalize_ticker


RATING_WORDS = r"(Strong Buy|Buy|Hold|Sell|Strong Sell|Neutral|Underperform|Outperform)"


def _investing_page_url(base_url: str, suffix: str = "") -> str:
    parts = urlsplit(base_url.strip())
    path = parts.path.rstrip("/") + suffix
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def rating_enrichment_urls(
    ticker: str,
    asset_type: str | None = None,
    include_research: bool = False,
    investing_url: str | None = None,
) -> list[dict[str, str]]:
    normalized = normalize_ticker(ticker)
    targets = [
        {
            "provider": "seeking_alpha",
            "data_type": "ratings",
            "url": f"https://seekingalpha.com/symbol/{normalized}/ratings/quant-ratings",
        },
        {
            "provider": "seeking_alpha",
            "data_type": "author_ratings",
            "url": f"https://seekingalpha.com/symbol/{normalized}/ratings/author-ratings",
        },
        {
            "provider": "seeking_alpha",
            "data_type": "sell_side_ratings",
            "url": f"https://seekingalpha.com/symbol/{normalized}/ratings/sell-side-ratings",
        },
        {
            "provider": "zacks",
            "data_type": "quote",
            "url": f"https://www.zacks.com/stock/quote/{normalized}",
        },
    ]
    if asset_type != "etf":
        targets.append(
            {
                "provider": "zacks",
                "data_type": "price_target_forecast",
                "url": f"https://www.zacks.com/stock/research/{normalized}/price-target-stock-forecast",
            }
        )
    if include_research and asset_type != "etf":
        targets.extend(
            [
                {"provider": "seeking_alpha", "data_type": "valuation", "url": f"https://seekingalpha.com/symbol/{normalized}/valuation/metrics"},
                {"provider": "seeking_alpha", "data_type": "growth", "url": f"https://seekingalpha.com/symbol/{normalized}/growth"},
                {"provider": "seeking_alpha", "data_type": "profitability", "url": f"https://seekingalpha.com/symbol/{normalized}/profitability"},
                {"provider": "seeking_alpha", "data_type": "momentum", "url": f"https://seekingalpha.com/symbol/{normalized}/momentum/performance"},
                {"provider": "seeking_alpha", "data_type": "estimates", "url": f"https://seekingalpha.com/symbol/{normalized}/earnings/estimates"},
                {"provider": "seeking_alpha", "data_type": "revisions", "url": f"https://seekingalpha.com/symbol/{normalized}/earnings/revisions"},
                {"provider": "seeking_alpha", "data_type": "peers", "url": f"https://seekingalpha.com/symbol/{normalized}/peers/comparison"},
                {"provider": "seeking_alpha", "data_type": "income_statement", "url": f"https://seekingalpha.com/symbol/{normalized}/income-statement"},
                {"provider": "seeking_alpha", "data_type": "cash_flow_statement", "url": f"https://seekingalpha.com/symbol/{normalized}/cash-flow-statement"},
                {"provider": "seeking_alpha", "data_type": "news", "url": f"https://seekingalpha.com/symbol/{normalized}/news"},
                {"provider": "seeking_alpha", "data_type": "analysis", "url": f"https://seekingalpha.com/symbol/{normalized}/analysis"},
                {"provider": "seeking_alpha", "data_type": "options_chain", "url": f"https://seekingalpha.com/symbol/{normalized}/options"},
                {"provider": "zacks", "data_type": "detailed_estimates", "url": f"https://www.zacks.com/stock/quote/{normalized}/detailed-earning-estimates"},
                {"provider": "zacks", "data_type": "insider_transactions", "url": f"https://www.zacks.com/stock/research/{normalized}/insider-transactions"},
                {"provider": "zacks", "data_type": "options_chain", "url": f"https://www.zacks.com/stock/quote/{normalized}/options-chain"},
                {"provider": "zacks", "data_type": "greeks_montage", "url": f"https://www.zacks.com/stock/quote/{normalized}/greeks-montage"},
            ]
        )
    if include_research and investing_url:
        base = _investing_page_url(investing_url)
        investing_targets = [{"provider": "investing_pro", "data_type": "overview", "url": base}]
        if asset_type != "etf":
            investing_targets.extend(
                [
                    {"provider": "investing_pro", "data_type": "financial_summary", "url": _investing_page_url(base, "-financial-summary")},
                    {"provider": "investing_pro", "data_type": "ratios", "url": _investing_page_url(base, "-ratios")},
                    {"provider": "investing_pro", "data_type": "cash_flow_statement", "url": _investing_page_url(base, "-cash-flow")},
                    {"provider": "investing_pro", "data_type": "forecast", "url": _investing_page_url(base, "-consensus-estimates")},
                    {"provider": "investing_pro", "data_type": "ownership", "url": _investing_page_url(base, "-ownership")},
                ]
            )
        investing_targets.extend(
            [
                {"provider": "investing_pro", "data_type": "news", "url": _investing_page_url(base, "-news")},
                {"provider": "investing_pro", "data_type": "analysis", "url": _investing_page_url(base, "-opinion")},
                {"provider": "investing_pro", "data_type": "options_chain", "url": _investing_page_url(base, "-options")},
            ]
        )
        # Once discovery has resolved the instrument, capture its Investing pages
        # immediately so the mapping and extraction form one visible workflow.
        targets = investing_targets + targets
    return targets


def required_enrichment_data_types(
    asset_type: str | None = None,
    include_polygon: bool = True,
    include_research: bool = False,
    include_investing: bool = False,
) -> set[str]:
    required = {
        "seeking_alpha:quant",
        "seeking_alpha:analysts",
        "seeking_alpha:wall_street",
        "zacks:rank",
    }
    if include_polygon:
        required.add("polygon:previous_close")
    if asset_type != "etf":
        required.add("seeking_alpha:price_target")
        required.add("zacks:price_target")
        if include_research:
            required.update(
                {
                    "seeking_alpha:valuation_metrics",
                    "seeking_alpha:growth_metrics",
                    "seeking_alpha:profitability_metrics",
                    "seeking_alpha:momentum_metrics",
                    "seeking_alpha:estimates",
                    "seeking_alpha:revisions",
                    "seeking_alpha:peer_comparison",
                    "seeking_alpha:income_statement",
                    "seeking_alpha:cash_flow_statement",
                    "seeking_alpha:news_items",
                    "seeking_alpha:analysis_items",
                    "seeking_alpha:options_chain",
                    "zacks:detailed_estimates",
                    "zacks:insider_transactions",
                    "zacks:greeks_montage",
                }
            )
    if include_research and include_investing:
        required.update(
            {
                "investing_pro:overview",
                "investing_pro:news_items",
                "investing_pro:analysis_items",
                "investing_pro:options_chain",
            }
        )
        if asset_type != "etf":
            required.update(
                {
                    "investing_pro:financial_summary",
                    "investing_pro:ratios",
                    "investing_pro:cash_flow_statement",
                    "investing_pro:forecast",
                    "investing_pro:ownership",
                }
            )
    return required


def parse_seeking_alpha_ratings(ticker: str, text: str) -> list[dict[str, Any]]:
    normalized = normalize_ticker(ticker)
    compact = _compact_text(text)
    snapshots: list[dict[str, Any]] = []
    snapshots.extend(_parse_seeking_alpha_page_data_lines(normalized, text))
    rating_patterns = [
        (
            "quant",
            rf"(SA Quant Rating\s+{RATING_WORDS}(?:\s+([0-9]+(?:\.[0-9]+)?))?)",
        ),
        (
            "analysts",
            rf"(SA Analysts Rating\s+{RATING_WORDS}(?:\s+([0-9]+(?:\.[0-9]+)?))?)",
        ),
        (
            "wall_street",
            rf"(Wall Street Rating\s+{RATING_WORDS}(?:\s+([0-9]+(?:\.[0-9]+)?))?)",
        ),
    ]
    for rating_type, pattern in rating_patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if not match:
            continue
        snapshots.append(
            _snapshot(
                ticker=normalized,
                provider="seeking_alpha",
                rating_type=rating_type,
                rating=_title_rating(match.group(2)),
                score=float(match.group(3)) if len(match.groups()) >= 3 and match.group(3) else None,
                price_target=None,
                source_text=match.group(1),
            )
        )
    snapshots.extend(_parse_seeking_alpha_visible_rating_blocks(normalized, compact, snapshots))
    snapshots.extend(_parse_seeking_alpha_visible_rating_lines(normalized, text, snapshots))
    snapshots.extend(_parse_seeking_alpha_json_like_ratings(normalized, compact, snapshots))

    target_match = re.search(
        r"((?:(?:Wall Street\s+)?price target|priceTarget)\s*(?:=)?\s*\$?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?))",
        compact,
        flags=re.IGNORECASE,
    )
    detailed_target = _parse_seeking_alpha_price_target(normalized, compact)
    if detailed_target:
        snapshots.append(detailed_target)
    elif target_match:
        snapshots.append(
            _snapshot(
                ticker=normalized,
                provider="seeking_alpha",
                rating_type="price_target",
                rating="Wall Street price target",
                score=None,
                price_target=_money(target_match.group(2)),
                source_text=target_match.group(1),
            )
        )
    ranking = parse_seeking_alpha_quant_ranking(normalized, text)
    if ranking:
        snapshots.append(ranking)
    return snapshots


def _parse_seeking_alpha_page_data_lines(
    normalized_ticker: str,
    text: str,
) -> list[dict[str, Any]]:
    snapshots = []
    line_patterns = [
        (
            "quant",
            rf"((?:SA_DATA\s+)?[^\n\r=]*(?:quantRating|quant_rating)[^\n\r=]*=\s*['\"]?{RATING_WORDS})",
            [
                r"(?:quantRating|quant_rating)[^\n\r=]*(?:score|Score)[^\n\r=]*=\s*([0-9]+(?:\.[0-9]+)?)",
                r"(?:quantRating|quant_rating)[^\n\r=]*\s+score\s*=\s*([0-9]+(?:\.[0-9]+)?)",
            ],
        ),
        (
            "analysts",
            rf"((?:SA_DATA\s+)?[^\n\r=]*(?:authorsRating|authors_rating|authorRating|author_rating|authorRatings)[^\n\r=]*=\s*['\"]?{RATING_WORDS})",
            [
                r"(?:authorsRating|authors_rating|authorRating|author_rating|authorRatings)[^\n\r=]*(?:score|Score)[^\n\r=]*=\s*([0-9]+(?:\.[0-9]+)?)",
                r"(?:authorRatings|authorsRating|authorRating)[^\n\r=]*\s+score\s*=\s*([0-9]+(?:\.[0-9]+)?)",
            ],
        ),
        (
            "wall_street",
            rf"((?:SA_DATA\s+)?[^\n\r=]*(?:sellSideRating|sell_side_rating|sellSideRatings|wallStreetRating|wall_street_rating)[^\n\r=]*=\s*['\"]?{RATING_WORDS})",
            [
                r"(?:sellSideRating|sell_side_rating|sellSideRatings|wallStreetRating|wall_street_rating)[^\n\r=]*(?:score|Score)[^\n\r=]*=\s*([0-9]+(?:\.[0-9]+)?)",
                r"(?:sellSideRatings|sellSideRating|wallStreetRating)[^\n\r=]*\s+score\s*=\s*([0-9]+(?:\.[0-9]+)?)",
            ],
        ),
    ]
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for rating_type, pattern, score_patterns in line_patterns:
            match = re.search(pattern, stripped, flags=re.IGNORECASE)
            if not match:
                continue
            snapshots.append(
                _snapshot(
                    ticker=normalized_ticker,
                    provider="seeking_alpha",
                    rating_type=rating_type,
                    rating=_title_rating(match.group(2)),
                    score=_first_float(text, score_patterns),
                    price_target=None,
                    source_text=match.group(1),
                )
            )
            break
    return snapshots


def _parse_seeking_alpha_visible_rating_blocks(
    normalized_ticker: str,
    compact: str,
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    label_patterns = [
        ("quant", r"(?:SA\s+)?Quant Rating"),
        ("analysts", r"SA Analysts'?\s+Rating|Author(?:s)? Rating|Seeking Alpha Analysts'?\s+Rating"),
        ("wall_street", r"Wall St\.?\s+Analysts'?\s+Rating|Wall Street Rating|Sell Side Rating"),
    ]
    snapshots = []
    for rating_type, label_pattern in label_patterns:
        if _has_rating_type(existing + snapshots, rating_type):
            continue
        matches = list(
            re.finditer(
                rf"(({label_pattern})\s+{RATING_WORDS}(?:\s+RATING:\s*(?:Strong Buy|Buy|Hold|Sell|Strong Sell|Neutral|Underperform|Outperform))?(?:\s+([0-9]+(?:\.[0-9]+)?))?)",
                compact,
                flags=re.IGNORECASE,
            )
        )
        # The page repeats the rating label, and only one copy carries the score.
        match = next((item for item in matches if item.group(4)), matches[0] if matches else None)
        if not match:
            continue
        snapshots.append(
            _snapshot(
                ticker=normalized_ticker,
                provider="seeking_alpha",
                rating_type=rating_type,
                rating=_title_rating(match.group(3)),
                score=float(match.group(4)) if match.group(4) else None,
                price_target=None,
                source_text=match.group(1),
            )
        )
    return snapshots


def _parse_seeking_alpha_visible_rating_lines(
    normalized_ticker: str,
    text: str,
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    label_patterns = [
        ("quant", r"(?:SA\s+)?Quant Rating"),
        ("analysts", r"SA Analysts'?\s+Rating|SA Analyst Rating|Author(?:s)? Rating"),
        ("wall_street", r"Wall St\.?\s+(?:Analysts'?\s+)?Ratings?|Wall Street Rating|Sell Side Ratings?"),
    ]
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    snapshots: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        for rating_type, label_pattern in label_patterns:
            if _has_rating_type(existing + snapshots, rating_type):
                continue
            if not re.fullmatch(label_pattern, line, flags=re.IGNORECASE):
                continue
            parsed = _rating_after_visible_label(lines, index + 1, label_patterns)
            if not parsed:
                continue
            rating, score, end_index = parsed
            source_text = " ".join(lines[index : end_index + 1])
            snapshots.append(
                _snapshot(
                    ticker=normalized_ticker,
                    provider="seeking_alpha",
                    rating_type=rating_type,
                    rating=_title_rating(rating),
                    score=score,
                    price_target=None,
                    source_text=source_text,
                )
            )
    return snapshots


def _rating_after_visible_label(
    lines: list[str],
    start_index: int,
    label_patterns: list[tuple[str, str]],
) -> tuple[str, float | None, int] | None:
    rating: str | None = None
    rating_index: int | None = None
    for index in range(start_index, min(len(lines), start_index + 10)):
        line = lines[index]
        if any(re.fullmatch(pattern, line, flags=re.IGNORECASE) for _, pattern in label_patterns):
            return None
        rating_match = re.search(rf"RATING:\s*{RATING_WORDS}\b", line, flags=re.IGNORECASE)
        if rating_match:
            rating = rating_match.group(1)
            rating_index = index
            break
    if rating is None or rating_index is None:
        return None
    score = None
    end_index = rating_index
    for index in range(rating_index + 1, min(len(lines), rating_index + 4)):
        score_match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)", lines[index])
        if score_match:
            score = float(score_match.group(1))
            end_index = index
            break
    return rating, score, end_index


def _parse_seeking_alpha_json_like_ratings(
    normalized_ticker: str,
    compact: str,
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    field_specs = [
        ("quant", r"quantRating|quant_rating", r"quantRatingScore|quant_rating_score"),
        (
            "analysts",
            r"authorsRating|authors_rating|authorRating|author_rating|authorRatings",
            r"authorsRatingScore|authors_rating_score|authorRatingScore|author_rating_score|authorRatingsScore",
        ),
        (
            "wall_street",
            r"sellSideRating|sell_side_rating|sellSideRatings|wallStreetRating|wall_street_rating",
            r"sellSideRatingScore|sell_side_rating_score|sellSideRatingsScore|wallStreetRatingScore|wall_street_rating_score",
        ),
    ]
    snapshots = []
    for rating_type, value_keys, score_keys in field_specs:
        if _has_rating_type(existing + snapshots, rating_type):
            continue
        match = re.search(
            rf"((?:['\"]?(?:{value_keys})['\"]?\s*[:=]\s*['\"]?{RATING_WORDS}['\"]?))",
            compact,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        score = _first_float(
            compact,
            [rf"['\"]?(?:{score_keys})['\"]?\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)"],
        )
        snapshots.append(
            _snapshot(
                ticker=normalized_ticker,
                provider="seeking_alpha",
                rating_type=rating_type,
                rating=_title_rating(match.group(2)),
                score=score,
                price_target=None,
                source_text=match.group(1),
            )
        )
    return snapshots


def parse_zacks_ratings(ticker: str, text: str) -> list[dict[str, Any]]:
    normalized = normalize_ticker(ticker)
    compact = _compact_text(text)
    snapshots: list[dict[str, Any]] = []
    style_scores = _parse_zacks_style_scores(compact)
    industry_rank = _parse_zacks_industry_rank(compact)
    rank_match = re.search(
        rf"(Zacks Rank\s+#([1-5])\s+\(({RATING_WORDS})\))",
        compact,
        flags=re.IGNORECASE,
    )
    if rank_match:
        rank = int(rank_match.group(2))
        rating = _title_rating(rank_match.group(3))
        snapshots.append(
            _snapshot(
                ticker=normalized,
                provider="zacks",
                rating_type="rank",
                rating=f"Rank #{rank} {rating}",
                score=rank,
                price_target=None,
                source_text=rank_match.group(1),
                extra={"style_scores": style_scores, "industry_rank": industry_rank},
            )
        )
    else:
        dash_rank_match = re.search(
            rf"(Zacks Rank:?\s*(?:More Info\s*)?#?\s*([1-5])\s*[-(]\s*({RATING_WORDS})\)?)",
            compact,
            flags=re.IGNORECASE,
        )
        if dash_rank_match:
            rank = int(dash_rank_match.group(2))
            rating = _title_rating(dash_rank_match.group(3))
            snapshots.append(
                _snapshot(
                    ticker=normalized,
                    provider="zacks",
                    rating_type="rank",
                    rating=f"Rank #{rank} {rating}",
                    score=rank,
                    price_target=None,
                    source_text=dash_rank_match.group(1),
                    extra={"style_scores": style_scores, "industry_rank": industry_rank},
                )
            )

    detailed_target = _parse_zacks_price_target_forecast(normalized, compact)
    if detailed_target:
        snapshots.append(detailed_target)
        return snapshots

    target_match = re.search(
        r"(Price Target\s+\$?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?))",
        compact,
        flags=re.IGNORECASE,
    )
    if target_match:
        snapshots.append(
            _snapshot(
                ticker=normalized,
                provider="zacks",
                rating_type="price_target",
                rating="Zacks price target",
                score=None,
                price_target=_money(target_match.group(2)),
                source_text=target_match.group(1),
            )
        )
    return snapshots


def _parse_zacks_style_scores(compact: str) -> dict[str, str] | None:
    match = re.search(
        r"([A-F][+-]?)\W*Value\s*\|\s*([A-F][+-]?)\W*Growth\s*\|\s*"
        r"([A-F][+-]?)\W*Momentum\s*\|\s*([A-F][+-]?)\W*VGM",
        compact,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "value": match.group(1).upper(),
        "growth": match.group(2).upper(),
        "momentum": match.group(3).upper(),
        "vgm": match.group(4).upper(),
    }


def _parse_zacks_industry_rank(compact: str) -> str | None:
    match = re.search(
        r"Industry Rank:\s*(?:More Info\s*)?(.+?)\s+Industry:",
        compact,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def _parse_seeking_alpha_price_target(
    normalized_ticker: str,
    compact: str,
) -> dict[str, Any] | None:
    average = _first_money(
        compact,
        [
            r"Average Price Target\s+\$?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)",
            r"priceTarget\.average\s*=\s*\$?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)",
        ],
    )
    if average is None:
        return None
    high = _first_money(compact, [r"\bHigh\b:?\s+\$?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)"])
    low = _first_money(compact, [r"\bLow\b:?\s+\$?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)"])
    upside = _first_float(compact, [r"\+?(-?[0-9]+(?:\.[0-9]+)?)%\s+Upside"])
    source_parts = [f"Average Price Target {average:,.2f}"]
    if high is not None:
        source_parts.append(f"High {high:,.2f}")
    if low is not None:
        source_parts.append(f"Low {low:,.2f}")
    if upside is not None:
        source_parts.append(f"Upside {upside:g}%")
    return _snapshot(
        ticker=normalized_ticker,
        provider="seeking_alpha",
        rating_type="price_target",
        rating="Wall Street price target",
        score=None,
        price_target=average,
        source_text="; ".join(source_parts),
        extra={
            "price_target_high": high,
            "price_target_low": low,
            "price_target_upside_pct": upside,
            "source_reported_upside_pct": upside,
            "implied_last_close_from_reported_upside": _implied_last_close(
                average,
                upside,
            ),
        },
    )


def _parse_zacks_price_target_forecast(
    normalized_ticker: str,
    compact: str,
) -> dict[str, Any] | None:
    average = _first_money(
        compact,
        [r"Average Price Target\s+\$?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)"],
    )
    if average is None:
        return None
    high = _first_money(
        compact,
        [r"Highest Price Target\s+\$?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)"],
    )
    low = _first_money(
        compact,
        [r"Lowest Price Target\s+\$?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)"],
    )
    upside = _first_float(
        compact,
        [r"Upside to Average Price Target\s+\+?(-?[0-9]+(?:\.[0-9]+)?)%"],
    )
    last_close = _first_money(
        compact,
        [r"Last Close\s+\$?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)"],
    )
    analyst_count = _first_int(compact, [r"Analyst Price Targets\s+\(([0-9]+)\)"])
    source_parts = [f"Average Price Target ${average:,.2f}"]
    if high is not None:
        source_parts.append(f"Highest ${high:,.2f}")
    if low is not None:
        source_parts.append(f"Lowest ${low:,.2f}")
    if upside is not None:
        source_parts.append(f"Upside {upside:g}%")
    if last_close is not None:
        source_parts.append(f"Last Close ${last_close:,.2f}")
    return _snapshot(
        ticker=normalized_ticker,
        provider="zacks",
        rating_type="price_target",
        rating="Zacks price target",
        score=None,
        price_target=average,
        source_text="; ".join(source_parts),
        extra={
            "price_target_high": high,
            "price_target_low": low,
            "price_target_upside_pct": upside,
            "source_reported_upside_pct": upside,
            "last_close": last_close,
            "source_last_close": last_close,
            "analyst_count": analyst_count,
        },
    )


class TickerRatingEnrichmentService:
    def __init__(
        self,
        fetcher: ArticleContentFetcherProtocol,
        repository: RunRepository,
        polygon_client=None,
        include_research: bool = False,
        investing_mapping_path: str | Path | None = None,
    ):
        self.fetcher = fetcher
        self.repository = repository
        self.polygon_client = polygon_client
        self.include_research = include_research
        self.investing_mapper = InvestingInstrumentMapper(
            fetcher=fetcher,
            mapping_path=investing_mapping_path,
        )
        self.investing_urls = self.investing_mapper.urls

    def enrich_ticker(
        self,
        run_id: int,
        ticker: str,
        asset_type: str | None = None,
        company_name: str | None = None,
        target_keys: set[tuple[str, str]] | None = None,
        zacks_forecast_for_detailed_estimates: bool = False,
    ) -> dict[str, int]:
        attempted = 0
        saved = 0
        failed = 0
        if self.polygon_client is not None and target_keys is None:
            attempted += 1
            try:
                snapshot = self.polygon_client.previous_close(normalize_ticker(ticker))
                if snapshot is None:
                    failed += 1
                    self.repository.save_ticker_enrichment(
                        run_id=run_id,
                        ticker=ticker,
                        provider="polygon",
                        data_type="previous_close",
                        data={},
                        status="failed",
                        failure_reason="Polygon previous close unavailable",
                    )
                else:
                    self.repository.save_ticker_enrichment(
                        run_id=run_id,
                        ticker=ticker,
                        provider="polygon",
                        data_type="previous_close",
                        data=snapshot,
                    )
                    saved += 1
            except Exception as exc:
                failed += 1
                self.repository.save_ticker_enrichment(
                    run_id=run_id,
                    ticker=ticker,
                    provider="polygon",
                    data_type="previous_close",
                    data={},
                    status="failed",
                    failure_reason=str(exc),
                )
        if asset_type == "etf":
            self.repository.save_ticker_enrichment(
                run_id=run_id,
                ticker=ticker,
                provider="zacks",
                data_type="price_target",
                data={
                    "rating_type": "price_target",
                    "reason": "ETF price targets are not applicable",
                },
                status="not_applicable",
                failure_reason=None,
            )
        investing_url = None
        if target_keys is None or any(provider == "investing_pro" for provider, _ in target_keys):
            investing_url = self._investing_url_for_ticker(
                run_id,
                ticker,
                company_name,
                asset_type,
            )
        for target in rating_enrichment_urls(
            ticker,
            asset_type=asset_type,
            include_research=self.include_research,
            investing_url=investing_url,
        ):
            if target_keys is not None and (target["provider"], target["data_type"]) not in target_keys:
                continue
            fallback_data_type = None
            if (
                zacks_forecast_for_detailed_estimates
                and target["provider"] == "zacks"
                and target["data_type"] == "detailed_estimates"
            ):
                fallback_data_type = target["data_type"]
                normalized = normalize_ticker(ticker)
                target = {
                    "provider": "zacks",
                    "data_type": "price_target_forecast",
                    "url": f"https://www.zacks.com/stock/research/{normalized}/price-target-stock-forecast",
                }
            attempted += 1
            try:
                content = self.fetcher.fetch(target["url"])
                if target["provider"] == "investing_pro" and not _same_investing_route(
                    target["url"],
                    content.final_url or target["url"],
                ):
                    if target["data_type"] == "options_chain":
                        self.repository.delete_ticker_enrichment(
                            run_id=run_id,
                            ticker=ticker,
                            provider=target["provider"],
                            data_type=target["data_type"],
                        )
                        self.repository.save_ticker_enrichment(
                            run_id=run_id,
                            ticker=ticker,
                            provider=target["provider"],
                            data_type=target["data_type"],
                            data={
                                "rating_type": target["data_type"],
                                "reason": "Investing.com does not expose an options route for this instrument",
                                "requested_url": target["url"],
                                "redirected_url": content.final_url,
                            },
                            source_url=content.final_url or target["url"],
                            status="not_applicable",
                            failure_reason=None,
                        )
                        saved += 1
                        continue
                    raise ValueError(
                        "Investing.com redirected away from the verified instrument route: "
                        f"requested {target['url']}; final {content.final_url or '<missing>'}"
                    )
                unavailable_reason = _structured_page_unavailable_reason(
                    content.extracted_text,
                    target["provider"],
                    target["data_type"],
                )
                if unavailable_reason:
                    self.repository.delete_ticker_enrichment(
                        run_id=run_id,
                        ticker=ticker,
                        provider=target["provider"],
                        data_type=target["data_type"],
                    )
                    self.repository.save_ticker_enrichment(
                        run_id=run_id,
                        ticker=ticker,
                        provider=target["provider"],
                        data_type=target["data_type"],
                        data={
                            "rating_type": target["data_type"],
                            "reason": unavailable_reason,
                        },
                        source_url=content.final_url or target["url"],
                        status="not_applicable",
                        failure_reason=None,
                    )
                    saved += 1
                    continue
                snapshots = _parse_snapshots(
                    ticker=ticker,
                    provider=target["provider"],
                    data_type=target["data_type"],
                    text=content.extracted_text,
                )
                if snapshots:
                    self.repository.delete_ticker_enrichment(
                        run_id=run_id,
                        ticker=ticker,
                        provider=target["provider"],
                        data_type=fallback_data_type or target["data_type"],
                    )
                    if fallback_data_type:
                        captured_fields = sorted(
                            {
                                field
                                for snapshot in snapshots
                                for field in ("rating", "price_target", "style_scores", "industry_rank")
                                if snapshot.get(field) is not None
                            }
                        )
                        self.repository.save_ticker_enrichment(
                            run_id=run_id,
                            ticker=ticker,
                            provider="zacks",
                            data_type=fallback_data_type,
                            data={
                                "rating_type": fallback_data_type,
                                "reason": "Detailed estimate tables unavailable; Zacks forecast fallback used",
                                "fallback_source_url": content.final_url or target["url"],
                                "captured_fields": captured_fields,
                                "missing_fields": [
                                    "sales_estimates",
                                    "earnings_estimates",
                                    "revision_agreement",
                                    "consensus_trend",
                                    "earnings_surprise_history",
                                ],
                            },
                            source_url=content.final_url or target["url"],
                            status="not_applicable",
                            failure_reason=None,
                        )
                else:
                    failure_reason = _unparsed_rating_failure_reason(
                        content.extracted_text,
                        content.title,
                        target["data_type"],
                    )
                    no_data_reason = _research_page_without_data_reason(
                        target["provider"],
                        target["data_type"],
                        content.title,
                        content.extracted_text,
                    )
                    if failure_reason in {
                        "Source page unavailable (HTTP 404)",
                        "Rating data unavailable from source coverage",
                    }:
                        no_data_reason = failure_reason
                    if no_data_reason:
                        self.repository.delete_ticker_enrichment(
                            run_id=run_id,
                            ticker=ticker,
                            provider=target["provider"],
                            data_type=fallback_data_type or target["data_type"],
                        )
                        self.repository.save_ticker_enrichment(
                            run_id=run_id,
                            ticker=ticker,
                            provider=target["provider"],
                            data_type=fallback_data_type or target["data_type"],
                            data={
                                "rating_type": fallback_data_type or target["data_type"],
                                "reason": no_data_reason,
                            },
                            source_url=content.final_url or target["url"],
                            status="not_applicable",
                            failure_reason=None,
                        )
                        saved += 1
                        continue
                    failed += 1
                    self.repository.save_ticker_enrichment(
                        run_id=run_id,
                        ticker=ticker,
                        provider=target["provider"],
                        data_type=fallback_data_type or target["data_type"],
                        data={
                            "page_title": content.title,
                            "text_sample": str(content.extracted_text or "")[:500],
                            "text_char_count": len(str(content.extracted_text or "")),
                            **_rating_failure_diagnostics(content.extracted_text),
                        },
                        source_url=content.final_url or target["url"],
                        status="failed",
                        failure_reason=failure_reason,
                    )
                for snapshot in snapshots:
                    self.repository.save_ticker_enrichment(
                        run_id=run_id,
                        ticker=snapshot["ticker"],
                        provider=snapshot["provider"],
                        data_type=snapshot["rating_type"],
                        data=snapshot,
                        source_url=content.final_url,
                    )
                    saved += 1
            except Exception as exc:
                failed += 1
                self.repository.save_ticker_enrichment(
                    run_id=run_id,
                    ticker=ticker,
                    provider=target["provider"],
                    data_type=target["data_type"],
                    data={},
                    source_url=target["url"],
                    status="failed",
                    failure_reason=str(exc),
                )
        return {"attempted": attempted, "saved": saved, "failed": failed}

    def _investing_url_for_ticker(
        self,
        run_id: int,
        ticker: str,
        company_name: str | None,
        asset_type: str | None,
    ) -> str | None:
        if not self.include_research:
            return None
        normalized = normalize_ticker(ticker)
        try:
            result = self.investing_mapper.ensure_url(
                normalized,
                company_name,
                asset_type=asset_type,
            )
        except Exception as exc:
            self.repository.save_ticker_enrichment(
                run_id=run_id,
                ticker=normalized,
                provider="investing_pro",
                data_type="mapping",
                data={},
                status="failed",
                failure_reason=f"Automatic Investing.com mapping failed: {exc}",
            )
            return None
        if result is None or not result.canonical_url:
            self.repository.save_ticker_enrichment(
                run_id=run_id,
                ticker=normalized,
                provider="investing_pro",
                data_type="mapping",
                data=(result.row if result else {}),
                status="failed",
                failure_reason=(result.review_reason if result else "Automatic Investing.com mapping found no candidate"),
            )
            return None
        self.investing_urls[normalized] = result.canonical_url
        self.repository.save_ticker_enrichment(
            run_id=run_id,
            ticker=normalized,
            provider="investing_pro",
            data_type="mapping",
            data=result.row,
            source_url=result.canonical_url,
        )
        return result.canonical_url


def _same_investing_route(requested_url: str, final_url: str) -> bool:
    requested = urlsplit(str(requested_url or "").strip())
    final = urlsplit(str(final_url or "").strip())
    requested_host = requested.netloc.lower().removeprefix("www.")
    final_host = final.netloc.lower().removeprefix("www.")
    return (
        requested.scheme == final.scheme == "https"
        and requested_host == final_host == "investing.com"
        and requested.path.rstrip("/") == final.path.rstrip("/")
        and requested.query == final.query
    )


def _parse_snapshots(ticker: str, provider: str, data_type: str, text: str) -> list[dict[str, Any]]:
    if provider == "seeking_alpha":
        if data_type in {
            "valuation", "growth", "profitability", "momentum", "estimates", "revisions",
            "peers", "income_statement", "cash_flow_statement", "news", "analysis",
            "options_chain",
        }:
            if data_type == "options_chain":
                return parse_seeking_alpha_options(ticker, text)
            return parse_seeking_alpha_research(ticker, data_type, text)
        return parse_seeking_alpha_ratings(ticker, text)
    if provider == "zacks":
        if data_type == "detailed_estimates":
            return parse_zacks_detailed_estimates(ticker, text)
        if data_type == "insider_transactions":
            return parse_zacks_insider_transactions(ticker, text)
        if data_type in {"options_chain", "greeks_montage"}:
            return parse_zacks_options(ticker, data_type, text)
        return parse_zacks_ratings(ticker, text)
    if provider == "investing_pro":
        return parse_investing_research(ticker, data_type, text)
    return []


def _load_investing_urls(path: str | Path | None) -> dict[str, str]:
    return load_investing_urls(path)


def _unparsed_rating_failure_reason(
    text: str,
    title: str | None = None,
    data_type: str | None = None,
) -> str:
    normalized = f"{title or ''} {text or ''}".lower()
    if "403 forbidden" in normalized or "permission to access this resource" in normalized:
        return "Source access blocked (HTTP 403)"
    if "error 404" in normalized or "page not found" in normalized:
        return "Source page unavailable (HTTP 404)"
    if "temporarily down for maintenance" in normalized or "please check back soon" in normalized:
        return "Source temporarily unavailable"
    if "zacks search results" in normalized:
        return "Rating data unavailable from source coverage"
    strong_bot_markers = [
        "pardon our interruption",
        "made us think you were a bot",
    ]
    if any(marker in normalized for marker in strong_bot_markers):
        return "Rating page blocked by source bot verification"
    loaded_zacks_quote_markers = [
        "zacks rank more info",
        "stock price today - zacks",
        "most viewed stocks on zacks.com",
    ]
    if any(marker in normalized for marker in loaded_zacks_quote_markers):
        return "No rating snapshot parsed from page text"
    unavailable_markers = [
        "rating is not available",
        "ratings are not available",
        "no sa analysts ratings",
        "no wall st. ratings",
        "not enough data",
        "not covered",
        "no analyst coverage",
        "no ratings available",
        "showratings.sell_side_rating = false",
        "showratings.quant_rating = false",
        "showratings.author_rating = false",
    ]
    rating_page_types = {"ratings", "author_ratings", "sell_side_ratings", "quote", "price_target_forecast"}
    if (data_type is None or data_type in rating_page_types) and any(
        marker in normalized for marker in unavailable_markers
    ):
        return "Rating data unavailable from source coverage"
    bot_markers = [
        "access to this page has been denied",
        "press & hold to confirm",
        "before we continue",
        "incapsula incident",
        "request unsuccessful",
        "captcha",
    ]
    if any(marker in normalized for marker in bot_markers):
        return "Rating page blocked by source bot verification"
    locked_markers = [
        "go premium to see",
        "locked. go premium",
        "view ratings",
        "subscribe now",
    ]
    if any(marker in normalized for marker in locked_markers):
        return "Rating page is locked or premium-gated"
    return "No rating snapshot parsed from page text"


def _structured_page_unavailable_reason(text: str, provider: str, data_type: str) -> str | None:
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("EQUITY_PAGE_UNAVAILABLE "):
            continue
        try:
            payload = json.loads(line.removeprefix("EQUITY_PAGE_UNAVAILABLE "))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if payload.get("provider") == provider and payload.get("data_type") == data_type:
            return str(payload.get("reason") or "Provider does not supply data for this page")
    return None


def _research_page_without_data_reason(
    provider: str,
    data_type: str,
    title: str | None,
    text: str,
) -> str | None:
    normalized_title = str(title or "").lower()
    raw_text = str(text or "")
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line.startswith("EQUITY_TABLE_MISSING "):
            continue
        try:
            payload = json.loads(line.removeprefix("EQUITY_TABLE_MISSING "))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if payload.get("provider") == provider and payload.get("data_type") == data_type:
            return str(payload.get("reason") or "Provider does not supply data for this page")
    if (
        provider == "zacks"
        and data_type == "insider_transactions"
        and "insider trans" in normalized_title
        and len(raw_text) >= 3000
        and "EQUITY_INSIDER_TXN " not in raw_text
        and "EQUITY_RESEARCH_TABLE " not in raw_text
    ):
        return "Zacks does not provide an insider-transaction table for this security"
    return None


def _rating_failure_diagnostics(text: str) -> dict[str, Any]:
    raw = str(text or "")
    if not raw:
        return {}
    keywords = [
        "SA_DATA",
        "Quant Rating",
        "quantRating",
        "currentQuantRating",
        "Author Rating",
        "SA Analysts",
        "authorsRating",
        "authorRatings",
        "Wall St",
        "Sell Side",
        "sellSideRating",
        "sellSideRatings",
        "Average Price Target",
        "priceTarget",
    ]
    lower = raw.lower()
    hits = [keyword for keyword in keywords if keyword.lower() in lower]
    if not hits:
        return {}
    first_positions = [lower.find(keyword.lower()) for keyword in hits]
    first_position = min(position for position in first_positions if position >= 0)
    start = max(0, first_position - 300)
    end = min(len(raw), first_position + 1200)
    return {
        "relevant_text_sample": raw[start:end],
        "diagnostic_keyword_hits": hits,
    }


def _snapshot(
    ticker: str,
    provider: str,
    rating_type: str,
    rating: str,
    score: float | int | None,
    price_target: float | None,
    source_text: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = {
        "ticker": ticker,
        "provider": provider,
        "rating_type": rating_type,
        "rating": rating,
        "score": score,
        "price_target": price_target,
        "currency": "USD",
        "source_text": _compact_text(source_text),
    }
    if extra:
        snapshot.update({key: value for key, value in extra.items() if value is not None})
    return snapshot


def _has_rating_type(snapshots: list[dict[str, Any]], rating_type: str) -> bool:
    return any(snapshot.get("rating_type") == rating_type for snapshot in snapshots)


def _compact_text(text: str) -> str:
    return " ".join(str(text or "").split())


def _title_rating(value: str) -> str:
    return " ".join(word.capitalize() for word in value.split())


def _money(value: str) -> float:
    return float(value.replace(",", ""))


def _first_money(compact: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            return _money(match.group(1))
    return None


def _first_float(compact: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            return float(match.group(1).replace(",", ""))
    return None


def _first_int(compact: str, patterns: list[str]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def _implied_last_close(target: float | None, upside_pct: float | None) -> float | None:
    if target is None or upside_pct is None:
        return None
    denominator = 1 + upside_pct / 100
    if denominator == 0:
        return None
    return round(target / denominator, 2)


_GRADE = re.compile(r"^(A\+|A|A-|B\+|B|B-|C\+|C|C-|D\+|D|D-|F)$")
_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_RATING_TOKENS = {"STRONG", "BUY", "HOLD", "SELL"}


def parse_seeking_alpha_quant_ranking(ticker: str, text: str) -> dict[str, Any] | None:
    """Quant ranking (overall / sector / industry) and the daily Quant Rating History table from the
    /symbol/X/ratings/quant-ratings page (added 2026-11-14 for the agency: rating momentum + sector rank)."""
    def rank(label: str):
        m = re.search(label + r"\s*\n?\s*([0-9,]+)\s+out of\s+([0-9,]+)", text)
        return (int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))) if m else (None, None)
    overall, sector, industry = rank("Ranked Overall"), rank("Ranked in Sector"), rank("Ranked in Industry")
    sec_m = re.search(r"QUANT RANKING\s*\n\s*Sector\s*\n\s*([^\n]+)\s*\n\s*Industry\s*\n\s*([^\n]+)", text)
    history = []
    start = text.find("QUANT RATING HISTORY")
    if start >= 0:
        tokens = [t for t in re.split(r"[\t\n]+", text[start:start + 60000]) if t.strip()]
        i = 0
        while i < len(tokens) and len(history) < 400:
            dm = _DATE.match(tokens[i].strip())
            if not dm:
                i += 1
                continue
            row = {"date": f"{dm.group(3)}-{dm.group(1)}-{dm.group(2)}"}
            j = i + 1
            try:
                row["price"] = float(tokens[j].replace(",", "").replace("$", ""))
                j += 1
            except (ValueError, IndexError):
                i += 1
                continue
            words = []
            while j < len(tokens) and tokens[j].strip().upper() in _RATING_TOKENS:
                words.append(tokens[j].strip().title())
                j += 1
            if j < len(tokens) and tokens[j].strip().upper().startswith("RATING:"):
                if not words:
                    words = [tokens[j].split(":", 1)[1].strip().title()]
                j += 1
            row["rating"] = " ".join(words) or None
            try:
                row["score"] = float(tokens[j])
                j += 1
            except (ValueError, IndexError):
                row["score"] = None
            grades = []
            while j < len(tokens) and len(grades) < 5 and _GRADE.match(tokens[j].strip()):
                grades.append(tokens[j].strip())
                j += 1
            for k, g in zip(("valuation", "growth", "profitability", "momentum", "eps_revisions"), grades):
                row[k] = g
            history.append(row)
            i = j
    if sector[0] is None and not history:
        return None
    pct = round((1 - (sector[0] - 1) / sector[1]) * 100, 1) if sector[0] and sector[1] else None
    return _snapshot(
        ticker=ticker, provider="seeking_alpha", rating_type="quant_ranking",
        rating=f"Sector rank {sector[0]}/{sector[1]}" if sector[0] else "Quant history",
        score=pct, price_target=None, source_text="Quant ranking and history",
        extra={"rank_overall": overall[0], "total_overall": overall[1], "rank_sector": sector[0], "total_sector": sector[1],
               "rank_industry": industry[0], "total_industry": industry[1], "sector_percentile": pct,
               "sector": sec_m.group(1).strip() if sec_m else None, "industry": sec_m.group(2).strip() if sec_m else None,
               "history": history},
    )
