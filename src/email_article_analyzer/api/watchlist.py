from fastapi import APIRouter, File, HTTPException, UploadFile

from email_article_analyzer.watchlist import parse_watchlist_file

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.post("/upload")
async def upload_watchlist(file: UploadFile = File(...)) -> dict:
    content = await file.read()
    try:
        parsed = parse_watchlist_file(file.filename or "watchlist.csv", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "columns": parsed.columns,
        "sample_rows": parsed.rows[:5],
        "row_count": len(parsed.rows),
    }
