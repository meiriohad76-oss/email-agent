import os
import sqlite3

import pytest

from email_article_analyzer.db_backup import backup_sqlite_database
from email_article_analyzer.db_backup import prune_sqlite_backups


def _create_database(path):
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('retained')")


def test_backup_sqlite_database_keeps_only_newest_backups(tmp_path):
    database = tmp_path / "app.db"
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    _create_database(database)
    for index in range(4):
        existing = backup_root / f"app-2026010{index}T000000Z-test.db"
        existing.write_bytes(b"old")
        os.utime(existing, (index + 1, index + 1))

    created = backup_sqlite_database(
        str(database),
        "new-backup",
        backup_root=backup_root,
        retention_count=3,
    )

    retained = sorted(backup_root.glob("app-*.db"))
    assert len(retained) == 3
    assert os.path.exists(created)
    with sqlite3.connect(created) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("retained",)


def test_prune_sqlite_backups_rejects_zero_retention(tmp_path):
    with pytest.raises(ValueError, match="at least 1"):
        prune_sqlite_backups(tmp_path, "app", ".db", retention_count=0)
