from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from email_article_analyzer.db_backup import backup_sqlite_database
from email_article_analyzer.providers.polygon import PolygonHttpClient
from email_article_analyzer.repositories import WatchlistRepository
from email_article_analyzer.watchlist import parse_watchlist_file
from email_article_analyzer.watchlist import normalize_ticker
from email_article_analyzer.watchlist import WatchlistService

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.post("/upload")
async def upload_watchlist(request: Request, file: UploadFile = File(...)) -> dict:
    content = await file.read()
    try:
        parsed = parse_watchlist_file(file.filename or "watchlist.csv", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ticker_column = _infer_ticker_column(parsed.columns)
    if ticker_column is None:
        raise HTTPException(
            status_code=400,
            detail="Could not find a ticker column. Use Symbol or Ticker.",
        )
    config = request.app.state.config
    validator = _FallbackTickerValidator(
        PolygonHttpClient(config.polygon_api_key)
        if config.polygon_api_key
        else None
    )
    service = WatchlistService(
        repository=WatchlistRepository(request.app.state.database_path),
        polygon_validator=validator,
    )
    try:
        backup_path = backup_sqlite_database(
            request.app.state.database_path,
            reason="before-watchlist-upload",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Database backup failed; watchlist was not changed",
                "error": str(exc),
            },
        ) from exc
    result = service.replace_active_watchlist(
        original_filename=file.filename or "watchlist.csv",
        parsed=parsed,
        ticker_column=ticker_column,
        optional_columns=_infer_optional_columns(parsed.columns),
    )
    duplicate_rows = [
        {
            "ticker": row.raw_ticker,
            "normalized_ticker": _normalize_for_response(row.raw_ticker),
            "reason": row.reason,
        }
        for row in result.invalid_rows
        if row.reason == "Duplicate ticker in upload"
    ]
    failed_rows = [row for row in result.invalid_rows if row.reason != "Duplicate ticker in upload"]
    saved_tickers = sorted(row.normalized_ticker for row in result.valid_rows)
    summary_parts = [
        (
            f"Saved {len(result.valid_rows)} unique tickers and "
            f"{result.portfolio_row_count} portfolio rows from {len(parsed.rows)} rows"
        ),
    ]
    skipped_parts = []
    if duplicate_rows:
        skipped_parts.append(
            f"preserved {len(duplicate_rows)} duplicate row"
            + ("" if len(duplicate_rows) == 1 else "s")
            + " as "
            + ("" if len(duplicate_rows) != 1 else "a ")
            + "portfolio lot"
            + ("" if len(duplicate_rows) == 1 else "s")
        )
    if failed_rows:
        skipped_parts.append(f"{len(failed_rows)} invalid row" + ("" if len(failed_rows) == 1 else "s"))
    if skipped_parts:
        summary_parts.append(" and ".join(skipped_parts))
    return {
        "columns": parsed.columns,
        "sample_rows": parsed.rows[:5],
        "row_count": len(parsed.rows),
        "ticker_column": ticker_column,
        "saved_count": len(result.valid_rows),
        "unique_ticker_count": len(result.valid_rows),
        "portfolio_row_count": result.portfolio_row_count,
        "duplicate_lot_count": result.duplicate_portfolio_row_count,
        "saved_tickers": saved_tickers,
        "duplicate_count": len(duplicate_rows),
        "duplicate_rows": duplicate_rows,
        "invalid_count": len(result.invalid_rows),
        "invalid_rows": [
            {
                "ticker": row.raw_ticker,
                "reason": row.reason,
            }
            for row in failed_rows[:20]
        ],
        "summary": "; ".join(summary_parts) + ".",
        "database_backup_path": backup_path,
    }


class _FallbackTickerValidator:
    def __init__(self, primary):
        self.primary = primary

    def validate_ticker(self, ticker: str) -> dict | None:
        if self.primary is None:
            return None
        if self.primary is not None:
            try:
                result = self.primary.validate_ticker(ticker)
            except Exception:
                return None
            if result is not None:
                return result
        return None


def _infer_ticker_column(columns: list[str]) -> str | None:
    preferred = ("symbol", "ticker")
    by_normalized = {column.strip().lower(): column for column in columns}
    for name in preferred:
        if name in by_normalized:
            return by_normalized[name]
    for column in columns:
        normalized = column.strip().lower()
        if "ticker" in normalized or "symbol" in normalized:
            return column
    return None


def _infer_optional_columns(columns: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    candidates = {
        "company_name": ("name", "company", "company name"),
        "sector": ("sector",),
        "priority": ("priority", "weight"),
        "notes": ("notes", "comment", "comments"),
    }
    by_normalized = {column.strip().lower(): column for column in columns}
    for field, names in candidates.items():
        for name in names:
            if name in by_normalized:
                mapping[field] = by_normalized[name]
                break
    return mapping


def _normalize_for_response(ticker: str) -> str:
    return normalize_ticker(ticker)
