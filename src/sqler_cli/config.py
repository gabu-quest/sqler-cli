"""Configuration and DB path resolution for sqler-cli."""

import os
from pathlib import Path


def get_global_db_path() -> Path:
    """Get the global database path (~/.sqler-cli/memory.db)."""
    return Path.home() / ".sqler-cli" / "memory.db"


def get_local_db_path() -> Path:
    """Get the local database path (CWD/.sqler-cli/memory.db)."""
    return Path.cwd() / ".sqler-cli" / "memory.db"


def has_local_db() -> bool:
    """Check if a local .sqler-cli/ directory exists in CWD."""
    return (Path.cwd() / ".sqler-cli").exists()


def get_db_path(override: str | None = None, use_global: bool = False) -> Path:
    """Resolve database path.

    Priority:
    1. --db PATH explicit override (highest)
    2. SQLER_CLI_DB env var
    3. --global flag → force global ~/.sqler-cli/
    4. .sqler-cli/ exists in CWD → use local
    5. fallback → global ~/.sqler-cli/

    Args:
        override: Explicit path passed via --db flag
        use_global: If True, skip local detection and use global

    Returns:
        Path to the SQLite database file
    """
    if override:
        return Path(override).expanduser().resolve()

    env_path = os.environ.get("SQLER_CLI_DB")
    if env_path:
        return Path(env_path).expanduser().resolve()

    if use_global:
        return get_global_db_path()

    # Check for local .sqler-cli/ in CWD
    if has_local_db():
        return get_local_db_path()

    # Default to global
    return get_global_db_path()


def ensure_db_dir(db_path: Path) -> None:
    """Ensure the parent directory for the database exists."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
