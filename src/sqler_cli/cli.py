"""CLI for sqler-cli memory management.

Persistent memory for LLMs. Store, search, and retrieve information
across sessions using SQLite FTS5 full-text search.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from .db import get_database
from .models import Memory
from sqler.query import F


# Keyword patterns for automatic tagging
AUTO_TAG_PATTERNS: dict[str, re.Pattern[str]] = {
    "api": re.compile(r"\b(api|endpoint|rest|graphql|http)\b", re.IGNORECASE),
    "database": re.compile(r"\b(database|db|sql|postgres|sqlite|mongo)\b", re.IGNORECASE),
    "config": re.compile(r"\b(config|configuration|settings|\.env|environment)\b", re.IGNORECASE),
    "auth": re.compile(r"\b(auth|authentication|jwt|oauth|password|login)\b", re.IGNORECASE),
    "error": re.compile(r"\b(error|exception|bug|fix|issue)\b", re.IGNORECASE),
    "security": re.compile(r"\b(security|secret|key|credential|token)\b", re.IGNORECASE),
}

# Main help text - shown with `mem --help`
MAIN_HELP = """
Persistent memory for LLMs. Store and search information across sessions.

QUICK START:
  mem remember "API key is in .env"              Store a memory
  mem remember "JWT auth setup" --auto-tag       Auto-detect tags
  mem remember "Note" --session work --importance 5
  mem recall "API"                               Search memories
  mem recall "API" --show-score --recent-first   With scores, by date
  mem update 42 "New content" --tag newtag       Update in-place
  mem list --session work --min-importance 4     Filter by session/importance
  mem dedupe --dry-run                           Find duplicates

COMMANDS:
  remember       Store a new memory
  recall         Search memories (FTS5)
  update         Modify a memory in-place
  list           Browse all memories
  forget         Delete memories
  tags           Manage tags (list/add/rm)
  dedupe         Find and merge duplicates
  rebuild-index  Rebuild FTS search index
  stats          Show database statistics
  export/import  Backup and restore

OUTPUT FORMATS:
  Default    Human-readable tables
  --json     JSON array for parsing (LLMs should use this)
  --quiet    Just IDs (for scripting)

DATABASE:
  Default location: .sqler-cli/memory.db
  Override with: --db PATH or SQLER_CLI_DB env var

Use 'mem COMMAND --help' for command-specific help.
"""

app = typer.Typer(
    name="mem",
    help=MAIN_HELP,
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

TAGS_HELP = """
Manage tags on memories.

COMMANDS:
  mem tags list              Show all tags with counts
  mem tags add ID TAG        Add tag to memory
  mem tags rm ID TAG         Remove tag from memory
"""
tags_app = typer.Typer(help=TAGS_HELP)
app.add_typer(tags_app, name="tags")

console = Console()

# Global options with detailed help
DbOption = Annotated[
    Optional[str],
    typer.Option(
        "--db",
        help="Database path. Overrides all other resolution.",
        envvar="SQLER_CLI_DB",
    ),
]
GlobalOption = Annotated[
    bool,
    typer.Option(
        "--global", "-g",
        help="Use global database (~/.sqler-cli/) even if local .sqler-cli/ exists.",
    ),
]
JsonOption = Annotated[
    bool,
    typer.Option(
        "--json", "-j",
        help="Output as JSON array. Use this for programmatic access.",
    ),
]
QuietOption = Annotated[
    bool,
    typer.Option(
        "--quiet", "-q",
        help="Minimal output: just IDs for scripting.",
    ),
]


def _ensure_db(db_path: Optional[str], use_global: bool = False) -> None:
    """Ensure database is initialized."""
    get_database(db_path, use_global=use_global)


def _auto_tag(content: str) -> list[str]:
    """Extract automatic tags from content based on keyword patterns."""
    tags = []
    text = f"{content}"
    for tag, pattern in AUTO_TAG_PATTERNS.items():
        if pattern.search(text):
            tags.append(tag)
    return tags


def _find_similar(memory: Memory, limit: int = 3, threshold: float = -5.0) -> list[tuple[Memory, float]]:
    """Find existing memories similar to the given one.

    Returns list of (memory, score) tuples for memories with score > threshold.
    Lower BM25 scores indicate higher relevance (more negative = better match).
    """
    # Extract key terms from content for search query
    words = memory.content.split()[:10]  # First 10 words
    if not words:
        return []

    query = " OR ".join(words)
    try:
        results = Memory.search_ranked(query, limit=limit + 1)  # +1 to exclude self
    except Exception:
        return []

    similar = []
    for result in results:
        # Skip the memory itself
        if result.model._id == memory._id:
            continue
        if result.score <= threshold:
            similar.append((result.model, result.score))
        if len(similar) >= limit:
            break

    return similar


def _output_memories(
    memories: list[Memory],
    as_json: bool = False,
    quiet: bool = False,
    scores: Optional[dict[int, float]] = None,
) -> None:
    """Output memories in the requested format.

    Args:
        memories: List of Memory objects to display
        as_json: Output as JSON
        quiet: Only output IDs
        scores: Optional dict mapping memory ID to BM25 score
    """
    if quiet:
        for m in memories:
            typer.echo(m._id)
        return

    if as_json:
        data = []
        for m in memories:
            item = {
                "id": m._id,
                "content": m.content,
                "tags": m.tags,
                "context": m.context,
                "source": m.source,
                "session_id": m.session_id,
                "supersedes": m.supersedes,
                "see_also": m.see_also,
                "source_url": m.source_url,
                "source_file": m.source_file,
                "importance": m.importance,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            }
            if scores and m._id in scores:
                item["score"] = scores[m._id]
            data.append(item)
        typer.echo(json.dumps(data, indent=2))
        return

    if not memories:
        typer.echo("No memories found.")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="dim", width=6)
    table.add_column("Content", max_width=60)
    table.add_column("Tags", style="cyan")
    if scores:
        table.add_column("Score", style="yellow", width=8)
    table.add_column("Created", style="green")

    for m in memories:
        created = m.created_at.strftime("%Y-%m-%d %H:%M") if m.created_at else "-"
        tags = ", ".join(m.tags) if m.tags else "-"
        content = m.content[:57] + "..." if len(m.content) > 60 else m.content
        row = [str(m._id), content, tags]
        if scores:
            score = scores.get(m._id, 0)
            row.append(f"{score:.2f}")
        row.append(created)
        table.add_row(*row)

    console.print(table)


REMEMBER_HELP = """
Store a new memory with optional tags and context.

EXAMPLES:
  mem remember "API key is in .env"
  mem remember "User prefers vim" --tag preferences --tag editor
  mem remember "JWT refresh needs work" --context "Auth module review"
  mem remember --file notes.txt --tag imported
  mem remember "The API uses JWT" --auto-tag      # Auto-detect: api, auth
  mem remember "Updated API URL" --supersedes 42  # Replaces old memory
  mem remember "Auth note" --session auth-refactor
  echo "content" | mem remember

OUTPUT:
  Default:   "Remembered (id=42)" + similar memories if found
  --json:    {"id": 42, "content": "...", "tags": [...]}
  --quiet:   42

FIELDS:
  content      The text to remember (required)
  tags         Categories for filtering (repeatable: -t foo -t bar)
  context      Why/where this was stored (also searchable via recall)
  source       Who created it: "user" (default), "claude", "file", etc.
  session      Session ID for context isolation
  importance   Priority level 1-5 (default: 3)
"""


@app.command(help=REMEMBER_HELP)
def remember(
    content: Annotated[
        Optional[str],
        typer.Argument(help="Text to remember. Omit to read from stdin."),
    ] = None,
    tag: Annotated[
        Optional[list[str]],
        typer.Option(
            "--tag", "-t",
            help="Tag for categorization. Repeat for multiple: -t foo -t bar",
        ),
    ] = None,
    context: Annotated[
        Optional[str],
        typer.Option(
            "--context", "-c",
            help="Why/where this was stored. Searchable via recall.",
        ),
    ] = None,
    source: Annotated[
        str,
        typer.Option(
            "--source", "-s",
            help="Who created this: 'user', 'claude', 'file', etc.",
        ),
    ] = "user",
    file: Annotated[
        Optional[Path],
        typer.Option(
            "--file", "-f",
            help="Read content from file instead of argument.",
        ),
    ] = None,
    session: Annotated[
        Optional[str],
        typer.Option(
            "--session",
            help="Session ID for grouping related memories.",
        ),
    ] = None,
    auto_tag: Annotated[
        bool,
        typer.Option(
            "--auto-tag",
            help="Automatically add tags based on content keywords.",
        ),
    ] = False,
    suggest_tags: Annotated[
        bool,
        typer.Option(
            "--suggest-tags",
            help="Show suggested tags and prompt to add them.",
        ),
    ] = False,
    supersedes: Annotated[
        Optional[int],
        typer.Option(
            "--supersedes",
            help="ID of memory this replaces.",
        ),
    ] = None,
    see_also: Annotated[
        Optional[list[int]],
        typer.Option(
            "--see-also",
            help="IDs of related memories. Repeatable.",
        ),
    ] = None,
    source_url: Annotated[
        Optional[str],
        typer.Option(
            "--source-url",
            help="URL where this information came from.",
        ),
    ] = None,
    source_file: Annotated[
        Optional[str],
        typer.Option(
            "--source-file",
            help="File path where this information came from (e.g., /path/file.py:42).",
        ),
    ] = None,
    importance: Annotated[
        int,
        typer.Option(
            "--importance", "-i",
            help="Importance level 1-5 (default: 3).",
            min=1,
            max=5,
        ),
    ] = 3,
    db: DbOption = None,
    use_global: GlobalOption = False,
    output_json: JsonOption = False,
    quiet: QuietOption = False,
) -> None:
    """Store a new memory."""
    _ensure_db(db, use_global)

    if file:
        if not file.exists():
            typer.echo(f"Error: File not found: {file}", err=True)
            raise typer.Exit(1)
        content = file.read_text()
    elif content is None:
        if not sys.stdin.isatty():
            content = sys.stdin.read().strip()
            if not content:
                typer.echo("Error: No content provided", err=True)
                raise typer.Exit(1)
        else:
            typer.echo("Error: No content provided", err=True)
            raise typer.Exit(1)

    # Build tag list
    tags = list(tag or [])

    # Handle auto-tagging
    if auto_tag or suggest_tags:
        suggested = _auto_tag(content)
        # Remove already-present tags
        suggested = [t for t in suggested if t not in tags]

        if suggest_tags and suggested and not quiet:
            typer.echo(f"Suggested tags: {', '.join(suggested)}")
            if typer.confirm("Add them?", default=False):
                tags.extend(suggested)
        elif auto_tag:
            tags.extend(suggested)

    memory = Memory(
        content=content,
        tags=tags,
        context=context,
        source=source,
        session_id=session,
        supersedes=supersedes,
        see_also=see_also or [],
        source_url=source_url,
        source_file=source_file,
        importance=importance,
    )
    memory.save()

    if quiet:
        typer.echo(memory._id)
    elif output_json:
        output_data = {
            "id": memory._id,
            "content": memory.content,
            "tags": memory.tags,
        }
        if auto_tag:
            auto_detected = _auto_tag(content)
            output_data["auto_tags"] = [t for t in auto_detected if t in memory.tags]
        typer.echo(json.dumps(output_data))
    else:
        tag_suffix = ""
        if auto_tag:
            auto_detected = _auto_tag(content)
            auto_added = [t for t in auto_detected if t in memory.tags]
            if auto_added:
                tag_suffix = f" [auto-tagged: {', '.join(auto_added)}]"
        typer.echo(f"Remembered (id={memory._id}){tag_suffix}")

        # Show similar existing memories (not in quiet or json mode)
        similar = _find_similar(memory)
        if similar:
            typer.echo("Similar existing memories:")
            for sim_mem, score in similar:
                sim_tags = f" (tags: {', '.join(sim_mem.tags)})" if sim_mem.tags else ""
                sim_content = sim_mem.content[:50] + "..." if len(sim_mem.content) > 50 else sim_mem.content
                typer.echo(f"  [{sim_mem._id}] {sim_content}{sim_tags}")


RECALL_HELP = """
Search memories using SQLite FTS5 full-text search.

Searches both 'content' and 'context' fields. Results ranked by relevance (BM25).

EXAMPLES:
  mem recall "API key"                    Find memories about API keys
  mem recall "database" --tag config      Search + filter by tag
  mem recall "auth" --limit 5             Limit results
  mem recall "user preferences" --json    JSON output for parsing
  mem recall "api" --show-score           Show BM25 relevance scores
  mem recall "api" --recent-first         Sort by date instead of relevance
  mem recall "api" --session auth-refactor  Search within session only
  mem recall "config" --min-importance 4  Only high-importance memories

SEARCH SYNTAX (FTS5):
  "API key"              Contains both words
  "API OR database"      Contains either word
  "config*"              Prefix match (config, configuration, ...)
  "\"exact phrase\""     Exact phrase match

OUTPUT:
  Default:   Rich table with ID, Content, Tags, Created
  --json:    JSON array of memory objects (includes score with --show-score)
  --quiet:   Just IDs, one per line
"""


@app.command(help=RECALL_HELP)
def recall(
    query: Annotated[
        str,
        typer.Argument(help="FTS5 search query. Searches content and context."),
    ],
    tag: Annotated[
        Optional[list[str]],
        typer.Option(
            "--tag", "-t",
            help="Filter results to only those with this tag. Repeatable.",
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(
            "--limit", "-n",
            help="Maximum number of results to return.",
        ),
    ] = 10,
    show_score: Annotated[
        bool,
        typer.Option(
            "--show-score",
            help="Show BM25 relevance scores in output.",
        ),
    ] = False,
    recent_first: Annotated[
        bool,
        typer.Option(
            "--recent-first",
            help="Sort by creation date (newest first) instead of relevance.",
        ),
    ] = False,
    session: Annotated[
        Optional[str],
        typer.Option(
            "--session",
            help="Only search memories in this session.",
        ),
    ] = None,
    min_importance: Annotated[
        Optional[int],
        typer.Option(
            "--min-importance",
            help="Only return memories with importance >= this value (1-5).",
            min=1,
            max=5,
        ),
    ] = None,
    boost_important: Annotated[
        bool,
        typer.Option(
            "--boost-important",
            help="Prioritize high-importance memories in results.",
        ),
    ] = False,
    db: DbOption = None,
    use_global: GlobalOption = False,
    output_json: JsonOption = False,
    quiet: QuietOption = False,
) -> None:
    """Search memories using full-text search."""
    _ensure_db(db, use_global)

    scores: Optional[dict[int, float]] = None

    if show_score or boost_important:
        # Use search_ranked to get scores
        ranked_results = Memory.search_ranked(query, limit=limit * 2)  # Get extra for filtering
        memories = [r.model for r in ranked_results]
        scores = {r.model._id: r.score for r in ranked_results}
    else:
        memories = Memory.search(query, limit=limit * 2)  # Get extra for filtering

    # Apply filters
    if tag:
        memories = [m for m in memories if any(t in m.tags for t in tag)]

    if session:
        memories = [m for m in memories if m.session_id == session]

    if min_importance:
        memories = [m for m in memories if m.importance >= min_importance]

    # Sort options
    if recent_first:
        memories.sort(key=lambda m: m.created_at or datetime.min, reverse=True)
    elif boost_important and scores:
        # Sort by importance first (desc), then by score (asc, more negative = better)
        memories.sort(key=lambda m: (-m.importance, scores.get(m._id, 0)))

    # Apply limit after filtering
    memories = memories[:limit]

    # Only pass scores if show_score is requested
    _output_memories(memories, output_json, quiet, scores if show_score else None)


LIST_HELP = """
List all memories with optional filters.

Unlike 'recall', this doesn't search - it lists everything (with filters).

EXAMPLES:
  mem list                          All memories
  mem list --tag preferences        Filter by tag
  mem list --since 2024-01-01       Created after date
  mem list --limit 10 --json        Last 10 as JSON
  mem list --session auth-refactor  Only session memories
  mem list --min-importance 4       Only important memories

OUTPUT:
  Default:   Rich table with ID, Content, Tags, Created
  --json:    JSON array of memory objects
  --quiet:   Just IDs, one per line
"""


@app.command("list", help=LIST_HELP)
def list_memories(
    tag: Annotated[
        Optional[list[str]],
        typer.Option(
            "--tag", "-t",
            help="Filter to memories with this tag. Repeatable.",
        ),
    ] = None,
    since: Annotated[
        Optional[str],
        typer.Option(
            "--since",
            help="Only memories created after this date (YYYY-MM-DD).",
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(
            "--limit", "-n",
            help="Maximum number of results.",
        ),
    ] = 50,
    session: Annotated[
        Optional[str],
        typer.Option(
            "--session",
            help="Only list memories in this session.",
        ),
    ] = None,
    min_importance: Annotated[
        Optional[int],
        typer.Option(
            "--min-importance",
            help="Only return memories with importance >= this value (1-5).",
            min=1,
            max=5,
        ),
    ] = None,
    db: DbOption = None,
    use_global: GlobalOption = False,
    output_json: JsonOption = False,
    quiet: QuietOption = False,
) -> None:
    """List all memories with optional filters."""
    _ensure_db(db, use_global)

    query = Memory.query()

    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            query = query.filter(F("created_at") >= since_dt.isoformat())
        except ValueError:
            typer.echo(f"Error: Invalid date format: {since}", err=True)
            raise typer.Exit(1)

    memories = query.limit(limit * 2).all()  # Get extra for filtering

    if tag:
        memories = [m for m in memories if any(t in m.tags for t in tag)]

    if session:
        memories = [m for m in memories if m.session_id == session]

    if min_importance:
        memories = [m for m in memories if m.importance >= min_importance]

    memories = memories[:limit]

    _output_memories(memories, output_json, quiet)


FORGET_HELP = """
Delete memories by ID or bulk delete by tag.

EXAMPLES:
  mem forget 42                              Delete memory #42
  mem forget --tag temporary --confirm       Delete all with 'temporary' tag
  mem forget --tag draft -y                  Same, -y skips confirmation

SAFETY:
  Single ID deletes immediately.
  Bulk tag deletes require --confirm/-y to prevent accidents.
"""


@app.command(help=FORGET_HELP)
def forget(
    memory_id: Annotated[
        Optional[int],
        typer.Argument(help="ID of memory to delete."),
    ] = None,
    tag: Annotated[
        Optional[str],
        typer.Option(
            "--tag", "-t",
            help="Delete ALL memories with this tag (requires --confirm).",
        ),
    ] = None,
    confirm: Annotated[
        bool,
        typer.Option(
            "--confirm", "-y",
            help="Skip confirmation prompt for bulk delete.",
        ),
    ] = False,
    db: DbOption = None,
    use_global: GlobalOption = False,
    quiet: QuietOption = False,
) -> None:
    """Delete a memory by ID or bulk delete by tag."""
    _ensure_db(db, use_global)

    if memory_id is None and tag is None:
        typer.echo("Error: Provide either a memory ID or --tag", err=True)
        raise typer.Exit(1)

    if memory_id is not None:
        memory = Memory.from_id(memory_id)
        if memory is None:
            typer.echo(f"Error: Memory {memory_id} not found", err=True)
            raise typer.Exit(1)
        memory.delete()
        if not quiet:
            typer.echo(f"Deleted memory {memory_id}")
        return

    memories = Memory.query().all()
    to_delete = [m for m in memories if tag in m.tags]

    if not to_delete:
        typer.echo(f"No memories found with tag '{tag}'")
        return

    if not confirm:
        typer.confirm(
            f"Delete {len(to_delete)} memories with tag '{tag}'?",
            abort=True,
        )

    for m in to_delete:
        m.delete()

    if not quiet:
        typer.echo(f"Deleted {len(to_delete)} memories")


TAGS_LIST_HELP = """
List all tags with their usage counts.

EXAMPLES:
  mem tags list          Show tags as table
  mem tags list --json   {"tag1": 5, "tag2": 3, ...}
"""


@tags_app.command("list", help=TAGS_LIST_HELP)
def tags_list(
    db: DbOption = None,
    use_global: GlobalOption = False,
    output_json: JsonOption = False,
) -> None:
    """List all tags with counts."""
    _ensure_db(db, use_global)

    memories = Memory.query().all()
    tag_counts: dict[str, int] = {}

    for m in memories:
        for t in m.tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1

    if output_json:
        typer.echo(json.dumps(tag_counts, indent=2))
        return

    if not tag_counts:
        typer.echo("No tags found.")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Tag", style="cyan")
    table.add_column("Count", justify="right")

    for tag, count in sorted(tag_counts.items()):
        table.add_row(tag, str(count))

    console.print(table)


TAGS_ADD_HELP = """
Add a tag to an existing memory.

EXAMPLE:
  mem tags add 42 important    Add 'important' tag to memory #42

Idempotent: adding an existing tag does nothing.
"""


@tags_app.command("add", help=TAGS_ADD_HELP)
def tags_add(
    memory_id: Annotated[int, typer.Argument(help="ID of memory to tag.")],
    tag: Annotated[str, typer.Argument(help="Tag to add.")],
    db: DbOption = None,
    use_global: GlobalOption = False,
    quiet: QuietOption = False,
) -> None:
    """Add a tag to a memory."""
    _ensure_db(db, use_global)

    memory = Memory.from_id(memory_id)
    if memory is None:
        typer.echo(f"Error: Memory {memory_id} not found", err=True)
        raise typer.Exit(1)

    if tag in memory.tags:
        if not quiet:
            typer.echo(f"Memory {memory_id} already has tag '{tag}'")
        return

    memory.tags = memory.tags + [tag]
    memory.save()

    if not quiet:
        typer.echo(f"Added tag '{tag}' to memory {memory_id}")


TAGS_RM_HELP = """
Remove a tag from a memory.

EXAMPLE:
  mem tags rm 42 draft    Remove 'draft' tag from memory #42

Idempotent: removing a non-existent tag does nothing.
"""


@tags_app.command("rm", help=TAGS_RM_HELP)
def tags_remove(
    memory_id: Annotated[int, typer.Argument(help="ID of memory to untag.")],
    tag: Annotated[str, typer.Argument(help="Tag to remove.")],
    db: DbOption = None,
    use_global: GlobalOption = False,
    quiet: QuietOption = False,
) -> None:
    """Remove a tag from a memory."""
    _ensure_db(db, use_global)

    memory = Memory.from_id(memory_id)
    if memory is None:
        typer.echo(f"Error: Memory {memory_id} not found", err=True)
        raise typer.Exit(1)

    if tag not in memory.tags:
        if not quiet:
            typer.echo(f"Memory {memory_id} doesn't have tag '{tag}'")
        return

    memory.tags = [t for t in memory.tags if t != tag]
    memory.save()

    if not quiet:
        typer.echo(f"Removed tag '{tag}' from memory {memory_id}")


INIT_HELP = """
Initialize a memory database.

By default, creates a LOCAL database in the current directory (.sqler-cli/).
Use --global to initialize the global database (~/.sqler-cli/).

EXAMPLES:
  mem init                 Create local .sqler-cli/ in current directory
  mem init --global        Initialize global ~/.sqler-cli/
  mem init --db /custom    Initialize at custom path

BEHAVIOR:
  - Local DB is used when .sqler-cli/ exists in current directory
  - Global DB (~/.sqler-cli/) is the fallback when no local exists
  - Use --global flag on any command to force global DB
"""


@app.command(help=INIT_HELP)
def init(
    use_global: Annotated[
        bool,
        typer.Option(
            "--global", "-g",
            help="Initialize global database (~/.sqler-cli/) instead of local.",
        ),
    ] = False,
    db: DbOption = None,
) -> None:
    """Initialize a database (local by default, or global with --global)."""
    from .config import get_global_db_path, get_local_db_path, ensure_db_dir

    if db:
        # Explicit path provided
        _ensure_db(db)
        from .config import get_db_path
        path = get_db_path(db)
        typer.echo(f"Database initialized at: {path}")
    elif use_global:
        # Initialize global
        path = get_global_db_path()
        ensure_db_dir(path)
        _ensure_db(None, use_global=True)
        typer.echo(f"Global database initialized at: {path}")
    else:
        # Initialize local (default)
        path = get_local_db_path()
        ensure_db_dir(path)
        _ensure_db(str(path))
        typer.echo(f"Local database initialized at: {path}")


STATS_HELP = """
Show database statistics: memory count, tags, size.

EXAMPLES:
  mem stats          Human-readable output
  mem stats --json   {"memory_count": 42, "tag_count": 5, "tags": {...}, ...}
"""


@app.command(help=STATS_HELP)
def stats(
    db: DbOption = None,
    use_global: GlobalOption = False,
    output_json: JsonOption = False,
) -> None:
    """Show database statistics."""
    _ensure_db(db, use_global)
    from .config import get_db_path

    path = get_db_path(db, use_global=use_global)
    memories = Memory.query().all()

    tag_counts: dict[str, int] = {}
    for m in memories:
        for t in m.tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1

    db_size = path.stat().st_size if path.exists() else 0

    stats_data = {
        "db_path": str(path),
        "db_size_bytes": db_size,
        "memory_count": len(memories),
        "tag_count": len(tag_counts),
        "tags": tag_counts,
    }

    if output_json:
        typer.echo(json.dumps(stats_data, indent=2))
        return

    typer.echo(f"Database: {path}")
    typer.echo(f"Size: {db_size:,} bytes")
    typer.echo(f"Memories: {len(memories)}")
    typer.echo(f"Unique tags: {len(tag_counts)}")


EXPORT_HELP = """
Export all memories to a JSON file for backup or transfer.

EXAMPLE:
  mem export backup.json
  mem export ~/memories-backup.json --db ./project/.sqler-cli/memory.db

The exported format can be imported with 'mem import'.
"""


@app.command("export", help=EXPORT_HELP)
def export_memories(
    output_file: Annotated[
        Path,
        typer.Argument(help="Path to write JSON export."),
    ],
    db: DbOption = None,
    use_global: GlobalOption = False,
) -> None:
    """Export all memories to JSON."""
    _ensure_db(db, use_global)

    memories = Memory.query().all()
    data = [
        {
            "content": m.content,
            "tags": m.tags,
            "context": m.context,
            "source": m.source,
            "session_id": m.session_id,
            "supersedes": m.supersedes,
            "see_also": m.see_also,
            "source_url": m.source_url,
            "source_file": m.source_file,
            "importance": m.importance,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        }
        for m in memories
    ]

    output_file.write_text(json.dumps(data, indent=2))
    typer.echo(f"Exported {len(memories)} memories to {output_file}")


IMPORT_HELP = """
Import memories from a JSON file.

EXAMPLE:
  mem import backup.json
  mem import memories.json --db ./new-project/.sqler-cli/memory.db

Expected format: JSON array of objects with 'content' field (required),
plus optional 'tags', 'context', 'source' fields.
"""


@app.command("import", help=IMPORT_HELP)
def import_memories(
    input_file: Annotated[
        Path,
        typer.Argument(help="Path to JSON file to import."),
    ],
    db: DbOption = None,
    use_global: GlobalOption = False,
    quiet: QuietOption = False,
) -> None:
    """Import memories from JSON."""
    _ensure_db(db, use_global)

    if not input_file.exists():
        typer.echo(f"Error: File not found: {input_file}", err=True)
        raise typer.Exit(1)

    data = json.loads(input_file.read_text())
    count = 0

    for item in data:
        memory = Memory(
            content=item["content"],
            tags=item.get("tags", []),
            context=item.get("context"),
            source=item.get("source", "imported"),
            session_id=item.get("session_id"),
            supersedes=item.get("supersedes"),
            see_also=item.get("see_also", []),
            source_url=item.get("source_url"),
            source_file=item.get("source_file"),
            importance=item.get("importance", 3),
        )
        memory.save()
        count += 1

    if not quiet:
        typer.echo(f"Imported {count} memories from {input_file}")


REBUILD_INDEX_HELP = """
Rebuild the FTS5 search index from all memories.

Use this for maintenance/recovery if search results seem incorrect.

EXAMPLE:
  mem rebuild-index
  mem rebuild-index --db /path/to/custom.db
"""


@app.command("rebuild-index", help=REBUILD_INDEX_HELP)
def rebuild_index(
    db: DbOption = None,
    use_global: GlobalOption = False,
) -> None:
    """Rebuild the FTS search index from all memories."""
    _ensure_db(db, use_global)
    count = Memory.rebuild_search_index()
    typer.echo(f"Rebuilt index with {count} memories")


UPDATE_HELP = """
Update an existing memory in-place without losing ID/timestamps.

EXAMPLES:
  mem update 42 "New content"             Replace content
  mem update 42 --tag newtag              Add a tag
  mem update 42 --context "New context"   Update context
  mem update 42 --clear-tags              Remove all tags
  mem update 42 --see-also 15 --see-also 23  Add related memories
  mem update 42 --importance 5            Mark as critical

Multiple flags can be combined in one command.
"""


@app.command(help=UPDATE_HELP)
def update(
    memory_id: Annotated[
        int,
        typer.Argument(help="ID of memory to update."),
    ],
    content: Annotated[
        Optional[str],
        typer.Argument(help="New content (optional)."),
    ] = None,
    tag: Annotated[
        Optional[list[str]],
        typer.Option(
            "--tag", "-t",
            help="Add tag(s) to the memory. Repeatable.",
        ),
    ] = None,
    context: Annotated[
        Optional[str],
        typer.Option(
            "--context", "-c",
            help="Update the context field.",
        ),
    ] = None,
    clear_tags: Annotated[
        bool,
        typer.Option(
            "--clear-tags",
            help="Remove all tags from the memory.",
        ),
    ] = False,
    session: Annotated[
        Optional[str],
        typer.Option(
            "--session",
            help="Set/change the session ID.",
        ),
    ] = None,
    supersedes: Annotated[
        Optional[int],
        typer.Option(
            "--supersedes",
            help="Set the ID of memory this replaces.",
        ),
    ] = None,
    see_also: Annotated[
        Optional[list[int]],
        typer.Option(
            "--see-also",
            help="Add related memory IDs. Repeatable.",
        ),
    ] = None,
    source_url: Annotated[
        Optional[str],
        typer.Option(
            "--source-url",
            help="Set/update the source URL.",
        ),
    ] = None,
    source_file: Annotated[
        Optional[str],
        typer.Option(
            "--source-file",
            help="Set/update the source file path.",
        ),
    ] = None,
    importance: Annotated[
        Optional[int],
        typer.Option(
            "--importance", "-i",
            help="Set importance level 1-5.",
            min=1,
            max=5,
        ),
    ] = None,
    db: DbOption = None,
    use_global: GlobalOption = False,
    output_json: JsonOption = False,
    quiet: QuietOption = False,
) -> None:
    """Update a memory in-place."""
    _ensure_db(db, use_global)

    memory = Memory.from_id(memory_id)
    if memory is None:
        typer.echo(f"Error: Memory {memory_id} not found", err=True)
        raise typer.Exit(1)

    # Track if anything changed
    changed = False

    if content is not None:
        memory.content = content
        changed = True

    if clear_tags:
        memory.tags = []
        changed = True
    elif tag:
        # Add new tags without duplicates
        existing = set(memory.tags)
        for t in tag:
            if t not in existing:
                memory.tags = memory.tags + [t]
                changed = True

    if context is not None:
        memory.context = context
        changed = True

    if session is not None:
        memory.session_id = session
        changed = True

    if supersedes is not None:
        memory.supersedes = supersedes
        changed = True

    if see_also:
        # Add new see_also IDs without duplicates
        existing = set(memory.see_also)
        for sid in see_also:
            if sid not in existing:
                memory.see_also = memory.see_also + [sid]
                changed = True

    if source_url is not None:
        memory.source_url = source_url
        changed = True

    if source_file is not None:
        memory.source_file = source_file
        changed = True

    if importance is not None:
        memory.importance = importance
        changed = True

    if not changed:
        if not quiet:
            typer.echo(f"No changes made to memory {memory_id}")
        return

    memory.save()

    if quiet:
        typer.echo(memory._id)
    elif output_json:
        typer.echo(
            json.dumps(
                {
                    "id": memory._id,
                    "content": memory.content,
                    "tags": memory.tags,
                    "updated": True,
                }
            )
        )
    else:
        typer.echo(f"Updated memory {memory_id}")


DEDUPE_HELP = """
Find and merge near-duplicate memories.

EXAMPLES:
  mem dedupe              Interactive: show groups, ask which to merge
  mem dedupe --dry-run    Just show duplicates without action
  mem dedupe --auto       Auto-merge keeping newest

MERGE BEHAVIOR:
  - Tags from all duplicates are combined
  - Newest content is kept
  - Older memories are deleted
"""


@app.command(help=DEDUPE_HELP)
def dedupe(
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Show duplicates without merging.",
        ),
    ] = False,
    auto: Annotated[
        bool,
        typer.Option(
            "--auto",
            help="Auto-merge keeping newest content.",
        ),
    ] = False,
    threshold: Annotated[
        float,
        typer.Option(
            "--threshold",
            help="BM25 score threshold for similarity (lower = more similar).",
        ),
    ] = -3.0,
    db: DbOption = None,
    use_global: GlobalOption = False,
    quiet: QuietOption = False,
) -> None:
    """Find and merge near-duplicate memories."""
    _ensure_db(db, use_global)

    all_memories = Memory.query().all()
    if len(all_memories) < 2:
        if not quiet:
            typer.echo("Not enough memories to deduplicate.")
        return

    # Find duplicate groups
    seen_ids: set[int] = set()
    duplicate_groups: list[list[Memory]] = []

    for memory in all_memories:
        if memory._id in seen_ids:
            continue

        # Search for similar memories
        similar = _find_similar(memory, limit=10, threshold=threshold)
        if not similar:
            continue

        group = [memory]
        for sim_mem, _score in similar:
            if sim_mem._id not in seen_ids:
                group.append(sim_mem)
                seen_ids.add(sim_mem._id)

        if len(group) > 1:
            seen_ids.add(memory._id)
            duplicate_groups.append(group)

    if not duplicate_groups:
        if not quiet:
            typer.echo("No duplicates found.")
        return

    if not quiet:
        typer.echo(f"Found {len(duplicate_groups)} duplicate group(s):\n")

    merged_count = 0

    for i, group in enumerate(duplicate_groups, 1):
        if not quiet:
            typer.echo(f"Group {i}:")
            for mem in group:
                content_preview = mem.content[:60] + "..." if len(mem.content) > 60 else mem.content
                tags_str = f" (tags: {', '.join(mem.tags)})" if mem.tags else ""
                created = mem.created_at.strftime("%Y-%m-%d") if mem.created_at else "?"
                typer.echo(f"  [{mem._id}] {content_preview}{tags_str} ({created})")
            typer.echo()

        if dry_run:
            continue

        # Determine whether to merge
        should_merge = auto
        if not auto and not quiet:
            should_merge = typer.confirm("Merge this group (keep newest)?", default=False)

        if should_merge:
            # Sort by created_at descending (newest first)
            group.sort(key=lambda m: m.created_at or datetime.min, reverse=True)
            keeper = group[0]

            # Collect all tags
            all_tags = set(keeper.tags)
            for mem in group[1:]:
                all_tags.update(mem.tags)

            # Update keeper with combined tags
            keeper.tags = list(all_tags)
            keeper.save()

            # Delete the rest
            for mem in group[1:]:
                mem.delete()

            merged_count += len(group) - 1
            if not quiet:
                typer.echo(f"  → Merged into [{keeper._id}], deleted {len(group) - 1} duplicate(s)\n")

    if not quiet and not dry_run:
        typer.echo(f"Merged {merged_count} duplicate(s) total.")


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
