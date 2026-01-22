"""Memory model for sqler-cli."""

from typing import Optional

from sqler import SQLerModel, SearchableMixin, TimestampMixin


class Memory(SearchableMixin, TimestampMixin, SQLerModel):
    """A stored memory with full-text search capabilities."""

    _table = "memories"

    content: str
    tags: list[str] = []
    context: Optional[str] = None
    source: str = "user"

    # Session isolation
    session_id: Optional[str] = None

    # Memory linking
    supersedes: Optional[int] = None  # ID of memory this replaces
    see_also: list[int] = []  # Related memory IDs

    # Source attribution
    source_url: Optional[str] = None
    source_file: Optional[str] = None

    # Prioritization
    importance: int = 3  # 1-5, default 3 (normal)

    class FTS:
        fields = ["content", "context"]
        tokenizer = "porter unicode61"
