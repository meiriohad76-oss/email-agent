from io import BytesIO

from openpyxl import Workbook

from email_article_analyzer.watchlist import parse_watchlist_file, normalize_ticker


def test_normalize_ticker_trims_uppercases_and_removes_exchange_suffix():
    assert normalize_ticker(" aapl ") == "AAPL"
    assert normalize_ticker("nasdaq:msft") == "MSFT"
    assert normalize_ticker("$tsla") == "TSLA"


def test_parse_watchlist_csv_returns_columns_and_rows():
    content = b"Symbol,Name\nAAPL,Apple Inc.\nMSFT,Microsoft\n"

    parsed = parse_watchlist_file("watchlist.csv", content)

    assert parsed.columns == ["Symbol", "Name"]
    assert parsed.rows == [
        {"Symbol": "AAPL", "Name": "Apple Inc."},
        {"Symbol": "MSFT", "Name": "Microsoft"},
    ]


def test_parse_watchlist_xlsx_returns_columns_and_rows():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Ticker", "Company"])
    sheet.append(["NVDA", "NVIDIA"])
    buffer = BytesIO()
    workbook.save(buffer)

    parsed = parse_watchlist_file("watchlist.xlsx", buffer.getvalue())

    assert parsed.columns == ["Ticker", "Company"]
    assert parsed.rows == [{"Ticker": "NVDA", "Company": "NVIDIA"}]
