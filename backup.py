#!/usr/bin/env python3
"""نسخ قاعدة البيانات ومفتاح تشفير التوكنات إلى مسارين منفصلين."""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.engine import make_url


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _backup_dirs() -> tuple[Path, Path]:
    database_dir = Path(
        os.getenv("DATABASE_BACKUP_DIR", "backups/database")
    ).expanduser()
    key_dir = Path(
        os.getenv("ENCRYPTION_KEY_BACKUP_DIR", "backups/encryption-key")
    ).expanduser()
    database_dir.mkdir(parents=True, exist_ok=True)
    key_dir.mkdir(parents=True, exist_ok=True)
    return database_dir, key_dir


def _backup_sqlite(database_url: str, destination: Path) -> None:
    database_path = make_url(database_url).database
    if not database_path or database_path == ":memory:":
        raise RuntimeError("لا يمكن نسخ قاعدة SQLite مؤقتة أو غير محددة")

    source = sqlite3.connect(database_path)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _backup_postgres(database_url: str, destination: Path) -> None:
    if not shutil.which("pg_dump"):
        raise RuntimeError("pg_dump غير موجود؛ ثبّت أداة PostgreSQL قبل النسخ")

    url = make_url(database_url)
    sync_url = url.set(drivername="postgresql")
    subprocess.run(
        ["pg_dump", "--format=custom", "--file", str(destination), str(sync_url)],
        check=True,
        capture_output=True,
        text=True,
    )


def _backup_database(database_url: str, destination: Path) -> None:
    if database_url.startswith("sqlite"):
        _backup_sqlite(database_url, destination)
    elif database_url.startswith(("postgresql", "postgres")):
        _backup_postgres(database_url, destination)
    else:
        raise RuntimeError("نوع DATABASE_URL غير مدعوم للنسخ الاحتياطي")


def _backup_encryption_key(encryption_key: str, destination: Path) -> None:
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(encryption_key + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, destination)
    destination.chmod(0o600)


def _remove_old_backups(directory: Path, retention_days: int) -> None:
    if retention_days <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    for path in directory.iterdir():
        if not path.is_file():
            continue
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if modified_at < cutoff:
            path.unlink()


def create_backups() -> tuple[Path, Path]:
    database_url = os.getenv("DATABASE_URL")
    encryption_key = os.getenv("ENCRYPTION_KEY")
    if not database_url:
        raise RuntimeError("DATABASE_URL غير موجود")
    if not encryption_key:
        raise RuntimeError("ENCRYPTION_KEY غير موجود")

    database_dir, key_dir = _backup_dirs()
    stamp = _timestamp()
    database_destination = database_dir / f"database-{stamp}.backup"
    key_destination = key_dir / f"encryption-key-{stamp}.txt"

    _backup_database(database_url, database_destination)
    try:
        _backup_encryption_key(encryption_key, key_destination)
    except Exception:
        database_destination.unlink(missing_ok=True)
        raise

    retention_days = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
    _remove_old_backups(database_dir, retention_days)
    _remove_old_backups(key_dir, retention_days)
    return database_destination, key_destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="لا تطبع مسارات النسخ الناتجة",
    )
    args = parser.parse_args()
    database_path, key_path = create_backups()
    if not args.quiet:
        print(f"Database backup: {database_path}")
        print(f"Encryption key backup: {key_path}")


if __name__ == "__main__":
    main()