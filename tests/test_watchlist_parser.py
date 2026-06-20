from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

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


def test_parse_watchlist_xlsx_ignores_invalid_conditional_formatting_metadata():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Ticker", "Company"])
    sheet.append(["NVDA", "NVIDIA"])
    buffer = BytesIO()
    workbook.save(buffer)
    broken_content = _add_invalid_conditional_formatting(buffer.getvalue())

    parsed = parse_watchlist_file("watchlist.xlsx", broken_content)

    assert parsed.columns == ["Ticker", "Company"]
    assert parsed.rows == [{"Ticker": "NVDA", "Company": "NVIDIA"}]


def _add_invalid_conditional_formatting(content: bytes) -> bytes:
    source = BytesIO(content)
    target = BytesIO()
    invalid_rule = (
        '<conditionalFormatting sqref="A1">'
        '<cfRule type="cellIs" priority="1" operator="invalidOperator">'
        "<formula>1</formula>"
        "</cfRule>"
        "</conditionalFormatting>"
    )
    with ZipFile(source, "r") as src, ZipFile(target, "w", ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                text = data.decode("utf-8")
                text = text.replace("</worksheet>", f"{invalid_rule}</worksheet>")
                data = text.encode("utf-8")
            dst.writestr(item, data)
    return target.getvalue()
