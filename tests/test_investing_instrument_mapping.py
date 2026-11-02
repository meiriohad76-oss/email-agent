import importlib.util
from pathlib import Path

from email_article_analyzer.investing_mapping import InvestingInstrumentMapper


SCRIPT_PATH = Path("scripts/map_investing_instruments.py")
SPEC = importlib.util.spec_from_file_location("map_investing_instruments", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_load_state_accepts_utf8_bom(tmp_path):
    state_path = tmp_path / "mapping-state.json"
    state_path.write_text('{"mapped":{"AAPL":{"ticker":"AAPL"}}}', encoding="utf-8-sig")

    state = MODULE.load_state(state_path)

    assert state["mapped"]["AAPL"]["ticker"] == "AAPL"


def test_parse_and_choose_exact_investing_listing():
    text = """
    INVESTING_RESULT AAPL Apple Inc Equity - NASDAQ equities | /equities/apple-computer-inc
    INVESTING_RESULT AAPL Apple Inc CDR Stock - Toronto equities | /equities/apple-cdr
    INVESTING_RESULT Stocks | /equities/
    """

    candidates = MODULE.parse_candidates(text)
    match = MODULE.choose_candidate("AAPL", "Apple Inc.", candidates)

    assert len(candidates) == 2
    assert match["canonical_url"] == "https://www.investing.com/equities/apple-computer-inc"
    assert match["exchange"] == "NASDAQ"
    assert match["ticker_exact"] is True


def test_choose_company_match_when_adr_symbol_is_not_available():
    text = """
    INVESTING_RESULT SIE Siemens AG Stock - Xetra | /equities/siemens
    INVESTING_RESULT SIE Siemens AG Stock - Frankfurt | /equities/siemens?cid=1222
    """

    candidates = MODULE.parse_candidates(text)
    match = MODULE.choose_candidate("SIEGY", "Siemens Aktiengesellschaft", candidates)
    confidence, review = MODULE.confidence_and_review("SIEGY", match)

    assert match is None
    assert confidence == "unmapped"
    assert "exact" in review


def test_parse_investing_instrument_id_from_cid():
    candidates = MODULE.parse_candidates(
        "INVESTING_RESULT TATT Tat Techno Stock - NASDAQ | /equities/tat-techno?cid=17311"
    )

    assert candidates[0]["instrument_id"] == "17311"


def test_parse_and_choose_investing_etf_listing():
    candidates = MODULE.parse_candidates(
        "INVESTING_RESULT QQQ Invesco QQQ Trust ETF - NASDAQ etf | /etfs/powershares-qqqq"
    )
    match = MODULE.choose_candidate("QQQ", "Invesco QQQ Trust", candidates)

    assert len(candidates) == 1
    assert match["canonical_url"] == "https://www.investing.com/etfs/powershares-qqqq"
    assert match["instrument_type"] == "Etf"
    assert match["exchange"] == "NASDAQ"
    assert match["ticker_exact"] is True


def test_etf_identity_gate_rejects_exact_ticker_stock_collision():
    candidates = MODULE.parse_candidates(
        "\n".join(
            [
                "INVESTING_RESULT QQQ Questcorp Mining Inc Stock - CBOE Canada equities | /equities/questcorp-mining",
                "INVESTING_RESULT QQQ Invesco QQQ Trust ETF - NASDAQ etfs | /etfs/powershares-qqqq",
            ]
        )
    )

    match = MODULE.choose_candidate(
        "QQQ",
        "Invesco QQQ Trust",
        candidates,
        expected_asset_type="etf",
    )

    assert match["canonical_url"] == "https://www.investing.com/etfs/powershares-qqqq"
    assert match["instrument_type"] == "Etf"


def test_runtime_mapper_replaces_low_confidence_cached_stock_for_etf(tmp_path):
    mapping_path = tmp_path / "investing.csv"
    mapping_path.write_text(
        "ticker,company,investing_symbol,investing_name,exchange,listing_kind,instrument_type,"
        "instrument_id,url_path,canonical_url,ticker_exact,company_similarity,match_score,"
        "confidence,review_reason,mapping_query,mapped_at,mapping_policy\n"
        "QQQ,,QQQ,Questcorp Mining Inc,CBOE Canada,local,Stock,,/equities/questcorp-mining,"
        "https://www.investing.com/equities/questcorp-mining,True,0.1,63.0,low,non-US listing,"
        "QQQ,2026-08-08T00:00:00Z,new_york_adr_first_v1\n",
        encoding="utf-8",
    )

    class Content:
        extracted_text = (
            "INVESTING_RESULT QQQ Questcorp Mining Inc Stock - CBOE Canada equities | "
            "/equities/questcorp-mining\n"
            "INVESTING_RESULT QQQ Invesco QQQ Trust ETF - NASDAQ etfs | "
            "/etfs/powershares-qqqq"
        )

    class Fetcher:
        def __init__(self):
            self.calls = []

        def fetch(self, url):
            self.calls.append(url)
            return Content()

    fetcher = Fetcher()
    mapper = InvestingInstrumentMapper(fetcher, mapping_path)

    result = mapper.ensure_url(
        "QQQ",
        "Invesco QQQ Trust",
        asset_type="etf",
    )

    assert fetcher.calls == ["https://www.investing.com/search/?q=QQQ"]
    assert result.canonical_url == "https://www.investing.com/etfs/powershares-qqqq"
    assert result.confidence == "high"
    assert "Questcorp" not in mapping_path.read_text(encoding="utf-8-sig")


def test_choose_us_adr_over_same_ticker_local_listing():
    candidates = MODULE.parse_candidates(
        "\n".join(
            [
                "INVESTING_RESULT SHEL Shell PLC ADR Stock - NYSE equities | /equities/shell-adr",
                "INVESTING_RESULT SHEL Shell PLC Stock - Amsterdam equities | /equities/shell-local",
            ]
        )
    )

    match = MODULE.choose_candidate("SHEL", "Shell plc", candidates)

    assert match["exchange"] == "NYSE"
    assert match["listing_kind"] == "ADR"


def test_new_york_adr_is_hard_priority_over_cleaner_local_name_match():
    candidates = MODULE.parse_candidates(
        "\n".join(
            [
                "INVESTING_RESULT ACME Acme Holdings ADR Stock - NYSE equities | /equities/acme-adr",
                "INVESTING_RESULT ACME Acme Corporation Stock - London equities | /equities/acme-local",
            ]
        )
    )

    match = MODULE.choose_candidate("ACME", "Acme Corporation", candidates)

    assert match["canonical_url"].endswith("/acme-adr")


def test_exact_otc_symbol_is_not_replaced_by_different_new_york_symbol():
    candidates = MODULE.parse_candidates(
        "\n".join(
            [
                "INVESTING_RESULT ABBNY ABB Ltd Stock - OTC Markets equities | /equities/abb-otc",
                "INVESTING_RESULT ABB ABB Ltd ADR Stock - NYSE equities | /equities/abb-ltd",
            ]
        )
    )

    match = MODULE.choose_candidate("ABBNY", "ABB Ltd", candidates)
    confidence, review = MODULE.confidence_and_review("ABBNY", match)

    assert match["investing_symbol"] == "ABBNY"
    assert match["exchange"] == "OTC MARKETS"
    assert confidence == "high"
    assert review == ""


def test_share_class_symbol_alias_matches_investing_lowercase_suffix():
    candidates = MODULE.parse_candidates(
        "INVESTING_RESULT BRKb Berkshire Hathaway B Stock - NYSE equities | "
        "/equities/berkshire-hathaway"
    )

    match = MODULE.choose_candidate("BRK.B", "Berkshire Hathaway Inc Class B", candidates)
    confidence, review = MODULE.confidence_and_review("BRK.B", match)

    assert match["canonical_url"] == "https://www.investing.com/equities/berkshire-hathaway"
    assert match["ticker_exact"] is True
    assert confidence == "high"
    assert review == ""


def test_runtime_mapper_retries_dot_class_ticker_with_hyphen_query(tmp_path):
    class Content:
        def __init__(self, text):
            self.extracted_text = text

    class Fetcher:
        def __init__(self):
            self.calls = []

        def fetch(self, url):
            self.calls.append(url)
            if "BRK-B" in url:
                return Content(
                    "INVESTING_RESULT BRKb Berkshire Hathaway B Stock - NYSE equities | "
                    "/equities/berkshire-hathaway"
                )
            return Content("")

    fetcher = Fetcher()
    mapper = InvestingInstrumentMapper(fetcher, tmp_path / "mapping.csv")

    result = mapper.ensure_url("BRK.B", "Berkshire Hathaway Inc Class B", asset_type="stock")

    assert fetcher.calls == [
        "https://www.investing.com/search/?q=BRK.B",
        "https://www.investing.com/search/?q=BRK-B",
    ]
    assert result.canonical_url == "https://www.investing.com/equities/berkshire-hathaway"
    assert result.confidence == "high"


def test_fresh_non_us_result_is_recorded_but_not_returned_as_usable_url(tmp_path):
    class Content:
        extracted_text = (
            "INVESTING_RESULT ABC Acme Corp Stock - Toronto equities | /equities/acme-corp"
        )

    class Fetcher:
        def fetch(self, _url):
            return Content()

    mapper = InvestingInstrumentMapper(Fetcher(), tmp_path / "mapping.csv")

    result = mapper.ensure_url("ABC", "Acme Corp", asset_type="stock")

    assert result.canonical_url is None
    assert result.confidence == "low"
    assert "non-US listing" in result.review_reason


def test_invalid_canonical_query_is_rejected_from_cache(tmp_path):
    mapping_path = tmp_path / "mapping.csv"
    mapping_path.write_text(
        "ticker,company,investing_symbol,investing_name,exchange,listing_kind,instrument_type,"
        "instrument_id,url_path,canonical_url,ticker_exact,company_similarity,match_score,"
        "confidence,review_reason,mapping_query,mapped_at,mapping_policy\n"
        "AAPL,Apple,AAPL,Apple Inc,NASDAQ,local,Stock,,/equities/apple-computer-inc,"
        "https://www.investing.com/equities/apple-computer-inc?utm_source=bad,True,1,110,"
        "high,,AAPL,2026-08-08T00:00:00Z,us_instrument_identity_v3\n",
        encoding="utf-8",
    )

    mapper = InvestingInstrumentMapper(object(), mapping_path)

    assert "AAPL" not in mapper.urls
