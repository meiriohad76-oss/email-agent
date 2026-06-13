from dataclasses import dataclass
import csv
from io import BytesIO, StringIO
import re

from openpyxl import load_workbook


@dataclass(frozen=True)
class ParsedWatchlist:
    columns: list[str]
    rows: list[dict[str, str]]


def normalize_ticker(value: str) -> str:
    ticker = value.strip().upper()
    ticker = ticker.removeprefix("$")
    if ":" in ticker:
        ticker = ticker.split(":", 1)[1]
    return re.sub(r"[^A-Z0-9.\-]", "", ticker)


def parse_watchlist_file(filename: str, content: bytes) -> ParsedWatchlist:
    lower_name = filename.lower()
    if lower_name.endswith(".csv"):
        return _parse_csv(content)
    if lower_name.endswith(".xlsx"):
        return _parse_xlsx(content)
    raise ValueError("Unsupported watchlist file type. Use CSV or XLSX.")


def _parse_csv(content: bytes) -> ParsedWatchlist:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(StringIO(text))
    columns = list(reader.fieldnames or [])
    rows = [
        {column: (row.get(column) or "").strip() for column in columns}
        for row in reader
    ]
    return ParsedWatchlist(columns=columns, rows=rows)


def _parse_xlsx(content: bytes) -> ParsedWatchlist:
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    sheet = workbook.active
    values = list(sheet.iter_rows(values_only=True))
    if not values:
        return ParsedWatchlist(columns=[], rows=[])
    columns = [str(cell or "").strip() for cell in values[0]]
    rows: list[dict[str, str]] = []
    for row in values[1:]:
        mapped = {
            columns[index]: str(row[index] or "").strip()
            for index in range(len(columns))
        }
        if any(mapped.values()):
            rows.append(mapped)
    return ParsedWatchlist(columns=columns, rows=rows)
