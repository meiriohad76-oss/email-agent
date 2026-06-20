from fastapi.testclient import TestClient

from email_article_analyzer.main import create_app


def test_upload_watchlist_returns_columns_and_sample_rows(tmp_path):
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    response = client.post(
        "/api/watchlist/upload",
        files={"file": ("watchlist.csv", b"Ticker,Name\nAAPL,Apple\n", "text/csv")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["columns"] == ["Ticker", "Name"]
    assert payload["sample_rows"] == [{"Ticker": "AAPL", "Name": "Apple"}]
    assert payload["row_count"] == 1


def test_upload_watchlist_returns_bad_request_for_unsupported_file(tmp_path):
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    response = client.post(
        "/api/watchlist/upload",
        files={"file": ("watchlist.txt", b"Ticker\nAAPL\n", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported watchlist file type. Use CSV or XLSX."
