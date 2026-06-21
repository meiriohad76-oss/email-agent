from fastapi.testclient import TestClient

from email_article_analyzer.main import create_app
from email_article_analyzer.repositories import WatchlistRepository


def test_upload_watchlist_returns_columns_and_sample_rows(tmp_path):
    db_path = str(tmp_path / "app.db")
    app = create_app(database_path=db_path)
    client = TestClient(app)

    response = client.post(
        "/api/watchlist/upload",
        files={
            "file": (
                "watchlist.csv",
                b"Ticker,Name\nAAPL,Apple\nQQQ,Invesco QQQ\n",
                "text/csv",
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["columns"] == ["Ticker", "Name"]
    assert payload["sample_rows"] == [
        {"Ticker": "AAPL", "Name": "Apple"},
        {"Ticker": "QQQ", "Name": "Invesco QQQ"},
    ]
    assert payload["row_count"] == 2
    assert payload["saved_count"] == 2
    assert payload["ticker_column"] == "Ticker"
    items = WatchlistRepository(db_path).list_active_items()
    assert [item["normalized_ticker"] for item in items] == ["AAPL", "QQQ"]


def test_upload_watchlist_returns_bad_request_for_unsupported_file(tmp_path):
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    response = client.post(
        "/api/watchlist/upload",
        files={"file": ("watchlist.txt", b"Ticker\nAAPL\n", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported watchlist file type. Use CSV or XLSX."
