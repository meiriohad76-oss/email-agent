from __future__ import annotations

import csv
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import parse_qs, quote, urljoin, urlparse

from email_article_analyzer.article_content import ArticleContentFetchError
from email_article_analyzer.watchlist import normalize_ticker


RESULT_PATTERN = re.compile(
    r"^INVESTING_RESULT\s+(?P<label>.+?)\s+\|\s+(?P<href>/(?:equities|etfs)/\S+)$"
)
LABEL_PATTERN = re.compile(
    r"^(?P<symbol>\S+)\s+(?P<name>.+?)\s+(?P<instrument_type>Stock|Equity|ETF)\s+-\s+(?P<exchange>.+)$",
    flags=re.IGNORECASE,
)
COMPANY_STOP_WORDS = {
    "ag",
    "company",
    "corp",
    "corporation",
    "group",
    "holdings",
    "inc",
    "incorporated",
    "limited",
    "ltd",
    "nv",
    "plc",
    "sa",
    "se",
    "the",
}
US_EXCHANGES = {
    "AMEX",
    "CBOE",
    "CBOE US",
    "NASDAQ",
    "NYSE",
    "NYSE AMERICAN",
    "NYSE ARCA",
    "OTC MARKETS",
}
NEW_YORK_EXCHANGES = US_EXCHANGES - {"OTC MARKETS"}
MAPPING_POLICY = "us_instrument_identity_v3"
FIELDNAMES = [
    "ticker",
    "company",
    "investing_symbol",
    "investing_name",
    "exchange",
    "listing_kind",
    "instrument_type",
    "instrument_id",
    "url_path",
    "canonical_url",
    "ticker_exact",
    "company_similarity",
    "match_score",
    "confidence",
    "review_reason",
    "mapping_query",
    "mapped_at",
    "mapping_policy",
]


@dataclass(frozen=True)
class InvestingMappingResult:
    ticker: str
    canonical_url: str | None
    confidence: str
    review_reason: str
    row: dict[str, object]


class InvestingInstrumentMapper:
    def __init__(
        self,
        fetcher,
        mapping_path: str | Path | None,
        *,
        timeout_seconds: float = 120.0,
    ):
        self.fetcher = fetcher
        self.mapping_path = Path(mapping_path) if mapping_path else None
        self.timeout_seconds = timeout_seconds
        self.rows = load_investing_rows(self.mapping_path)
        self.urls = {
            ticker: str(row.get("canonical_url") or "").strip()
            for ticker, row in self.rows.items()
            if cached_mapping_is_acceptable(row)
        }

    def ensure_url(
        self,
        ticker: str,
        company_name: str | None = None,
        asset_type: str | None = None,
    ) -> InvestingMappingResult | None:
        normalized = normalize_ticker(ticker)
        if not normalized:
            return None
        existing_url = self.urls.get(normalized)
        existing_row = self.rows.get(normalized, {})
        if existing_url and mapping_matches_asset_type(existing_row, asset_type):
            return InvestingMappingResult(
                ticker=normalized,
                canonical_url=existing_url,
                confidence="cached",
                review_reason="",
                row=dict(existing_row),
            )
        result = discover_investing_mapping(
            fetcher=self.fetcher,
            ticker=normalized,
            company_name=company_name,
            asset_type=asset_type,
            timeout_seconds=self.timeout_seconds,
        )
        if result is None:
            return None
        if result.canonical_url:
            self.urls[normalized] = result.canonical_url
            self.rows[normalized] = result.row
        if self.mapping_path is not None:
            upsert_investing_mapping(self.mapping_path, result.row)
        return result


def discover_investing_mapping(
    fetcher,
    ticker: str,
    company_name: str | None = None,
    asset_type: str | None = None,
    timeout_seconds: float = 120.0,
) -> InvestingMappingResult | None:
    normalized = normalize_ticker(ticker)
    company = str(company_name or "").strip()
    candidates: list[dict[str, str]] = []
    queries = ticker_search_queries(normalized)
    query = queries[0]
    match = None
    for query in queries:
        candidates = _merge_candidates(candidates, _capture_search_candidates(fetcher, query))
        match = choose_candidate(
            normalized,
            company or normalized,
            candidates,
            expected_asset_type=asset_type,
        )
        confidence, _ = confidence_and_review(normalized, match)
        if confidence == "high":
            break
    if company and confidence_and_review(normalized, match)[0] != "high":
        candidates = _merge_candidates(candidates, _capture_search_candidates(fetcher, company))
        match = choose_candidate(
            normalized,
            company,
            candidates,
            expected_asset_type=asset_type,
        )
        query = f"{query}+company"
    confidence, review_reason = confidence_and_review(normalized, match)
    row = {
        "ticker": normalized,
        "company": company,
        **(match or {}),
        "confidence": confidence,
        "review_reason": review_reason,
        "mapping_query": query,
        "mapped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mapping_policy": MAPPING_POLICY,
    }
    return InvestingMappingResult(
        ticker=normalized,
        canonical_url=(str(row.get("canonical_url") or "") or None) if confidence == "high" else None,
        confidence=confidence,
        review_reason=review_reason,
        row=row,
    )


def _capture_search_candidates(fetcher, query: str) -> list[dict[str, str]]:
    url = f"https://www.investing.com/search/?q={quote(query)}"
    try:
        content = fetcher.fetch(url)
    except ArticleContentFetchError:
        raise
    return parse_candidates(content.extracted_text)


def parse_candidates(text: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw_line in str(text or "").splitlines():
        result_match = RESULT_PATTERN.match(raw_line.strip())
        if not result_match:
            continue
        label = result_match.group("label")
        label_match = LABEL_PATTERN.match(label)
        if not label_match:
            continue
        href = result_match.group("href")
        key = (label_match.group("symbol").upper(), href)
        if key in seen:
            continue
        seen.add(key)
        parsed_url = urlparse(href)
        exchange = normalize_exchange(label_match.group("exchange"))
        candidates.append(
            {
                "investing_symbol": label_match.group("symbol").upper(),
                "investing_name": label_match.group("name").strip(),
                "instrument_type": label_match.group("instrument_type").title(),
                "exchange": exchange,
                "listing_kind": (
                    "ADR"
                    if re.search(r"\bADR\b", label_match.group("name"), flags=re.IGNORECASE)
                    else "OTC"
                    if exchange.upper() == "OTC MARKETS"
                    else "local"
                ),
                "url_path": href,
                "canonical_url": urljoin("https://www.investing.com", href),
                "instrument_id": (parse_qs(parsed_url.query).get("cid") or [""])[0],
            }
        )
    return candidates


def choose_candidate(
    ticker: str,
    company: str,
    candidates: list[dict[str, str]],
    expected_asset_type: str | None = None,
) -> dict[str, object] | None:
    eligible = [
        candidate
        for candidate in candidates
        if candidate_matches_asset_type(candidate, expected_asset_type)
        and ticker_identity_matches(ticker, str(candidate.get("investing_symbol") or ""))
    ]
    scored = [score_candidate(ticker, company, candidate) for candidate in eligible]
    if not scored:
        return None
    scored.sort(
        key=lambda item: (
            item["exchange"].upper() in US_EXCHANGES,
            not bool(urlparse(str(item["canonical_url"])).query),
            float(item["company_similarity"]),
            float(item["match_score"]),
        ),
        reverse=True,
    )
    return scored[0]


def candidate_matches_asset_type(
    candidate: dict[str, object],
    expected_asset_type: str | None,
) -> bool:
    expected = normalize_asset_type(expected_asset_type)
    if expected is None:
        return True
    instrument_type = str(candidate.get("instrument_type") or "").strip().lower()
    path = urlparse(str(candidate.get("canonical_url") or candidate.get("url_path") or "")).path
    if expected == "etf":
        return instrument_type == "etf" and path.startswith("/etfs/")
    return instrument_type in {"stock", "equity"} and path.startswith("/equities/")


def normalize_asset_type(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"etf", "etn", "fund"}:
        return "etf"
    if normalized in {"stock", "equity", "common stock", "cs", "adrc", "pfd"}:
        return "stock"
    return None


def cached_mapping_is_acceptable(row: dict[str, object]) -> bool:
    url = str(row.get("canonical_url") or "").strip()
    if not url:
        return False
    confidence = str(row.get("confidence") or "").strip().lower()
    if confidence != "high":
        return False
    ticker_exact = str(row.get("ticker_exact") or "").strip().lower()
    if ticker_exact not in {"1", "true", "yes"}:
        return False
    if str(row.get("mapping_policy") or "").strip() != MAPPING_POLICY:
        return False
    if normalize_exchange(str(row.get("exchange") or "")) not in US_EXCHANGES:
        return False
    if not ticker_identity_matches(
        str(row.get("ticker") or ""),
        str(row.get("investing_symbol") or ""),
    ):
        return False
    if not canonical_investing_root_is_valid(url):
        return False
    stored_type = normalize_asset_type(str(row.get("instrument_type") or ""))
    return stored_type is not None and candidate_matches_asset_type(row, stored_type)


def mapping_matches_asset_type(row: dict[str, object], expected_asset_type: str | None) -> bool:
    expected = normalize_asset_type(expected_asset_type)
    if not cached_mapping_is_acceptable(row):
        return False
    return expected is None or candidate_matches_asset_type(row, expected)


def score_candidate(ticker: str, company: str, candidate: dict[str, str]) -> dict[str, object]:
    exact_ticker = ticker_identity_matches(ticker, candidate["investing_symbol"])
    similarity = company_similarity(company, candidate["investing_name"])
    exchange_bonus = 15 if candidate["exchange"].upper() in US_EXCHANGES else 0
    score = (60 if exact_ticker else 0) + similarity * 35 + exchange_bonus
    return {
        **candidate,
        "ticker_exact": exact_ticker,
        "company_similarity": round(similarity, 4),
        "match_score": round(score, 2),
    }


def confidence_and_review(ticker: str, match: dict[str, object] | None) -> tuple[str, str]:
    if match is None:
        return "unmapped", "No exact Investing.com instrument candidate found"
    exact = bool(match["ticker_exact"])
    exchange = normalize_exchange(str(match["exchange"]))
    canonical_url = str(match.get("canonical_url") or "")
    confidence = (
        "high"
        if exact and exchange in US_EXCHANGES and canonical_investing_root_is_valid(canonical_url)
        else "low"
    )
    review_reasons = []
    if not exact:
        review_reasons.append("symbol differs from requested ticker")
    if exchange not in US_EXCHANGES:
        review_reasons.append(f"non-US listing ({exchange})")
    if not canonical_investing_root_is_valid(canonical_url):
        review_reasons.append("invalid Investing.com instrument root")
    return confidence, "; ".join(review_reasons)


def ticker_identity_matches(requested: str, candidate: str) -> bool:
    left = normalize_ticker(str(requested or ""))
    right = normalize_ticker(str(candidate or ""))
    if not left or not right:
        return False
    if left == right:
        return True
    return bool(("." in left or "-" in left) and ticker_identity_key(left) == ticker_identity_key(right))


def ticker_identity_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", normalize_ticker(str(value or "")))


def ticker_search_queries(ticker: str) -> list[str]:
    normalized = normalize_ticker(ticker)
    queries = [normalized]
    if "." in normalized:
        queries.append(normalized.replace(".", "-"))
    return list(dict.fromkeys(query for query in queries if query))


def normalize_exchange(value: str) -> str:
    exchange = re.sub(
        r"\s+(?:equities|etfs?)$",
        "",
        str(value or "").strip(),
        flags=re.IGNORECASE,
    )
    return " ".join(exchange.upper().split())


def canonical_investing_root_is_valid(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    host = parsed.netloc.lower().removeprefix("www.")
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme != "https" or host != "investing.com" or len(parts) != 2:
        return False
    if parts[0] not in {"equities", "etfs"} or not parts[1]:
        return False
    if parsed.fragment:
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    return not query or (set(query) == {"cid"} and len(query["cid"]) == 1 and query["cid"][0].isdigit())


def _merge_candidates(
    existing: list[dict[str, str]],
    discovered: list[dict[str, str]],
) -> list[dict[str, str]]:
    return list(
        {
            str(candidate.get("canonical_url") or candidate.get("url_path") or ""): candidate
            for candidate in existing + discovered
        }.values()
    )


def company_similarity(left: str, right: str) -> float:
    left_words = normalized_words(left)
    right_words = normalized_words(right)
    if not left_words or not right_words:
        return 0.0
    left_text = " ".join(left_words)
    right_text = " ".join(right_words)
    sequence = SequenceMatcher(None, left_text, right_text).ratio()
    overlap = len(set(left_words) & set(right_words)) / max(1, len(set(left_words) | set(right_words)))
    return max(sequence, overlap)


def normalized_words(value: str) -> list[str]:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[a-z0-9]+", ascii_value.lower())
    return [word for word in words if word not in COMPANY_STOP_WORDS]


def load_investing_urls(path: str | Path | None) -> dict[str, str]:
    if path is None:
        return {}
    mapping_path = Path(path)
    if not mapping_path.exists():
        return {}
    with mapping_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            normalize_ticker(row["ticker"]): row["canonical_url"].strip()
            for row in csv.DictReader(handle)
            if row.get("ticker") and row.get("canonical_url") and cached_mapping_is_acceptable(row)
        }


def load_investing_rows(path: str | Path | None) -> dict[str, dict[str, object]]:
    if path is None:
        return {}
    mapping_path = Path(path)
    if not mapping_path.exists():
        return {}
    with mapping_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            normalize_ticker(str(row.get("ticker") or "")): dict(row)
            for row in csv.DictReader(handle)
            if row.get("ticker")
        }


def upsert_investing_mapping(path: str | Path, row: dict[str, object]) -> None:
    mapping_path = Path(path)
    rows = _read_mapping_rows(mapping_path)
    normalized = normalize_ticker(str(row.get("ticker") or ""))
    rows = [existing for existing in rows if normalize_ticker(str(existing.get("ticker") or "")) != normalized]
    rows.append(row)
    rows.sort(key=lambda item: normalize_ticker(str(item.get("ticker") or "")))
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = mapping_path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in FIELDNAMES} for row in rows)
    temporary.replace(mapping_path)


def _read_mapping_rows(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))
