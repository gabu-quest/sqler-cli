"""Database initialization for sqler-cli."""

from pathlib import Path

from sqler import SQLerDB

from .config import ensure_db_dir, get_db_path
from .models import Memory


_db: SQLerDB | None = None


def get_database(db_path: str | None = None, use_global: bool = False) -> SQLerDB:
    """Get or create the database connection.

    Args:
        db_path: Optional override for database path
        use_global: If True, force global database

    Returns:
        Configured SQLerDB instance
    """
    global _db

    path = get_db_path(db_path, use_global=use_global)
    ensure_db_dir(path)

    if _db is None or str(path) != str(getattr(_db, "path", None)):
        _db = SQLerDB.on_disk(str(path))
        _init_schema(_db)

    return _db


def _init_schema(db: SQLerDB) -> None:
    """Initialize database schema and FTS index."""
    Memory.set_db(db)
    Memory.create_search_index(db)


def reset_database() -> None:
    """Reset the global database connection (for testing)."""
    global _db
    _db = None
