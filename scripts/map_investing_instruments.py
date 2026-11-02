from __future__ import annotations

import argparse
import csv
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import quote, urljoin, urlparse, parse_qs

import httpx


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    ROOT.parent
    / "trading system"
    / "outputs"
    / "sa_zacks_input_20260731"
    / "email_analyzer_watchlist.csv"
)
DEFAULT_OUTPUT = ROOT / "data" / "investing_instrument_mapping.csv"
DEFAULT_STATE = ROOT / "data" / "investing_instrument_mapping_state.json"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
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
    "AMEX", "CBOE", "CBOE US", "NASDAQ", "NYSE", "NYSE AMERICAN",
    "NYSE ARCA", "OTC MARKETS",
}
NEW_YORK_EXCHANGES = US_EXCHANGES - {"OTC MARKETS"}
MAPPING_POLICY = "us_instrument_identity_v3"


def normalized_words(value: str) -> list[str]:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[a-z0-9]+", ascii_value.lower())
    return [word for word in words if word not in COMPANY_STOP_WORDS]


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


def confidence_and_review(ticker: str, match: dict[str, object] | None) -> tuple[str, str]:
    if match is None:
        return "unmapped", "No exact Investing.com instrument candidate found"
    exact = bool(match["ticker_exact"])
    exchange = normalize_exchange(str(match["exchange"]))
    confidence = "high" if exact and exchange in US_EXCHANGES else "low"
    review_reasons = []
    if not exact:
        review_reasons.append("symbol differs from requested ticker")
    if exchange not in US_EXCHANGES:
        review_reasons.append(f"non-US listing ({exchange})")
    return confidence, "; ".join(review_reasons)


def ticker_identity_matches(requested: str, candidate: str) -> bool:
    left = re.sub(r"[^A-Z0-9.\-]", "", str(requested or "").strip().upper())
    right = re.sub(r"[^A-Z0-9.\-]", "", str(candidate or "").strip().upper())
    if not left or not right:
        return False
    if left == right:
        return True
    return bool(("." in left or "-" in left) and ticker_identity_key(left) == ticker_identity_key(right))


def ticker_identity_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def ticker_search_queries(ticker: str) -> list[str]:
    normalized = str(ticker or "").strip().upper()
    queries = [normalized]
    if "." in normalized:
        queries.append(normalized.replace(".", "-"))
    return list(dict.fromkeys(query for query in queries if query))


def normalize_exchange(value: str) -> str:
    exchange = re.sub(
        r"\s+(?:equities|etfs?)$", "", str(value or "").strip(), flags=re.IGNORECASE
    )
    return " ".join(exchange.upper().split())


def capture_search(client: httpx.Client, base_url: str, query: str, timeout: float) -> dict:
    response = client.post(
        f"{base_url}/api/browser-tasks/test-extract",
        json={
            "url": f"https://www.investing.com/search/?q={quote(query)}",
            "timeout_seconds": timeout,
            "include_full_text": True,
        },
    )
    response.raise_for_status()
    return response.json()


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"mapped": {}}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "ticker",
        "company",
        "sector",
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
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in fieldnames} for row in rows)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Map watchlist tickers to Investing.com instruments.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ticker", action="append", default=[])
    parser.add_argument("--force", action="store_true", help="Remap selected tickers already in state.")
    parser.add_argument(
        "--force-review",
        action="store_true",
        help="Remap existing rows that were flagged for listing review.",
    )
    args = parser.parse_args()

    with args.input.open("r", encoding="utf-8-sig", newline="") as handle:
        watchlist = list(csv.DictReader(handle))
    requested = {value.strip().upper() for value in args.ticker if value.strip()}
    if requested:
        watchlist = [row for row in watchlist if row["Ticker"].upper() in requested]

    state = load_state(args.state)
    mapped = state.setdefault("mapped", {})
    pending = []
    for row in watchlist:
        ticker = row["Ticker"].upper()
        existing = mapped.get(ticker, {})
        needs_review = bool(existing.get("review_reason"))
        if args.force or ticker not in mapped or (args.force_review and needs_review):
            pending.append(row)
    if args.limit is not None:
        pending = pending[: max(0, args.limit)]
    print(json.dumps({"watchlist": len(watchlist), "pending": len(pending)}), flush=True)

    with httpx.Client(timeout=httpx.Timeout(args.timeout + 30, connect=10.0)) as client:
        status = client.get(f"{args.base_url}/api/browser-tasks/status")
        status.raise_for_status()
        if status.json().get("status") != "connected":
            print(json.dumps({"error": "Chrome extension bridge is not connected"}), flush=True)
            return 2
        for index, source in enumerate(pending, start=1):
            ticker = source["Ticker"].strip().upper()
            company = source["Company"].strip()
            asset_type = (
                source.get("Asset Type")
                or source.get("asset_type")
                or source.get("Type")
                or source.get("Security Type")
            )
            print(f"[{index}/{len(pending)}] {ticker} {company}", flush=True)
            try:
                candidates = []
                query = ticker
                match = None
                for query in ticker_search_queries(ticker):
                    payload = capture_search(client, args.base_url, query, args.timeout)
                    candidates = list({
                        candidate["canonical_url"]: candidate
                        for candidate in candidates + parse_candidates(payload.get("extracted_text", ""))
                    }.values())
                    match = choose_candidate(
                        ticker, company, candidates, expected_asset_type=asset_type
                    )
                    if confidence_and_review(ticker, match)[0] == "high":
                        break
                if company and confidence_and_review(ticker, match)[0] != "high":
                    payload = capture_search(client, args.base_url, company, args.timeout)
                    company_candidates = parse_candidates(payload.get("extracted_text", ""))
                    combined = {
                        candidate["canonical_url"]: candidate
                        for candidate in candidates + company_candidates
                    }
                    match = choose_candidate(
                        ticker,
                        company,
                        list(combined.values()),
                        expected_asset_type=asset_type,
                    )
                    query = f"{ticker}+company"
                confidence, review_reason = confidence_and_review(ticker, match)
                row = {
                    "ticker": ticker,
                    "company": company,
                    "sector": source.get("Sector", ""),
                    **(match or {}),
                    "confidence": confidence,
                    "review_reason": review_reason,
                    "mapping_query": query,
                    "mapped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "mapping_policy": MAPPING_POLICY,
                }
            except Exception as exc:
                row = {
                    "ticker": ticker,
                    "company": company,
                    "sector": source.get("Sector", ""),
                    "confidence": "error",
                    "review_reason": str(exc),
                    "mapping_query": ticker,
                    "mapped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "mapping_policy": MAPPING_POLICY,
                }
            mapped[ticker] = row
            save_state(args.state, state)
            write_csv(args.output, [mapped[key] for key in sorted(mapped)])
            print(
                json.dumps(
                    {
                        "ticker": ticker,
                        "investing_symbol": row.get("investing_symbol"),
                        "exchange": row.get("exchange"),
                        "confidence": row.get("confidence"),
                        "review_reason": row.get("review_reason"),
                    }
                ),
                flush=True,
            )
            if index < len(pending):
                time.sleep(max(0.0, args.delay))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
