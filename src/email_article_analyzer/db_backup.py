from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import sqlite3


DEFAULT_BACKUP_RETENTION = 10


def backup_sqlite_database(
    database_path: str,
    reason: str,
    backup_root: str | Path | None = None,
    retention_count: int = DEFAULT_BACKUP_RETENTION,
) -> str:
    source_path = Path(database_path)
    if not source_path.exists():
        raise FileNotFoundError(f"Database not found: {database_path}")
    root = Path(backup_root) if backup_root is not None else source_path.parent / "backups"
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_reason = re.sub(r"[^A-Za-z0-9_.-]+", "-", reason).strip("-") or "backup"
    backup_path = root / f"{source_path.stem}-{timestamp}-{safe_reason}{source_path.suffix}"
    with sqlite3.connect(str(source_path)) as source:
        with sqlite3.connect(str(backup_path)) as destination:
            source.backup(destination)
    prune_sqlite_backups(root, source_path.stem, source_path.suffix, retention_count)
    return str(backup_path)


def prune_sqlite_backups(
    backup_root: str | Path,
    database_stem: str,
    database_suffix: str,
    retention_count: int = DEFAULT_BACKUP_RETENTION,
) -> list[str]:
    if retention_count < 1:
        raise ValueError("retention_count must be at least 1")
    root = Path(backup_root)
    if not root.exists():
        return []
    backups = sorted(
        root.glob(f"{database_stem}-*{database_suffix}"),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    removed: list[str] = []
    for backup in backups[retention_count:]:
        backup.unlink()
        removed.append(str(backup))
    return removed


def restore_sqlite_database(database_path: str, backup_path: str) -> None:
    source = Path(backup_path)
    if not source.exists():
        raise FileNotFoundError(f"Database backup not found: {backup_path}")
    destination = Path(database_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
