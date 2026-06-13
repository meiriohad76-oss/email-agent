from dataclasses import dataclass

from email_article_analyzer.db import initialize_database
from email_article_analyzer.repositories import WatchlistRepository
from email_article_analyzer.watchlist import ParsedWatchlist, WatchlistService


@dataclass
class FakePolygonValidator:
    valid_tickers: set[str]

    def validate_ticker(self, ticker: str):
        if ticker in self.valid_tickers:
            return {"ticker": ticker, "name": f"{ticker} Corp"}
        return None


def test_validate_mapping_splits_valid_and_invalid_rows(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    service = WatchlistService(
        repository=WatchlistRepository(db_path),
        polygon_validator=FakePolygonValidator({"AAPL"}),
    )
    parsed = ParsedWatchlist(
        columns=["Symbol", "Name"],
        rows=[
            {"Symbol": "AAPL", "Name": "Apple"},
            {"Symbol": "BAD!", "Name": "Broken"},
        ],
    )

    result = service.validate(
        parsed,
        ticker_column="Symbol",
        optional_columns={"company_name": "Name"},
    )

    assert [row.normalized_ticker for row in result.valid_rows] == ["AAPL"]
    assert result.invalid_rows[0].raw_ticker == "BAD!"


def test_replace_active_watchlist_deletes_old_rows_and_saves_valid_rows(tmp_path):
    db_path = str(tmp_path / "app.db")
    initialize_database(db_path)
    repository = WatchlistRepository(db_path)
    service = WatchlistService(
        repository=repository,
        polygon_validator=FakePolygonValidator({"AAPL", "MSFT"}),
    )
    first = ParsedWatchlist(columns=["Ticker"], rows=[{"Ticker": "AAPL"}])
    second = ParsedWatchlist(columns=["Ticker"], rows=[{"Ticker": "MSFT"}])

    service.replace_active_watchlist(
        "first.csv",
        first,
        ticker_column="Ticker",
        optional_columns={},
    )
    service.replace_active_watchlist(
        "second.csv",
        second,
        ticker_column="Ticker",
        optional_columns={},
    )

    items = repository.list_active_items()
    assert [item["normalized_ticker"] for item in items] == ["MSFT"]
