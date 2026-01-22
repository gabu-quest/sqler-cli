"""Test fixtures for sqler-cli."""

import os
import tempfile
from pathlib import Path

import pytest

from sqler_cli.db import reset_database


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create a temporary database path."""
    db_path = tmp_path / "test_memory.db"
    # Set the env var so get_db_path uses this path
    os.environ["SQLER_CLI_DB"] = str(db_path)
    yield db_path
    # Cleanup
    reset_database()
    if "SQLER_CLI_DB" in os.environ:
        del os.environ["SQLER_CLI_DB"]


@pytest.fixture
def temp_db_path(tmp_path: Path) -> str:
    """Return just the path string for --db flag testing."""
    db_path = tmp_path / "test_memory.db"
    return str(db_path)
