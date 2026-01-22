# sqler-cli (mem)

Persistent memory for LLMs. Store, search, and retrieve information across sessions using SQLite FTS5 full-text search.

## Why This Exists

LLMs have no persistent memory between sessions. This CLI provides a simple way to:

- **Remember** things: project conventions, user preferences, API endpoints, decisions made
- **Recall** them later: full-text search finds relevant memories instantly
- **Organize** with tags, sessions, and importance levels
- **Link** related memories together with supersedes/see-also chains
- **Deduplicate** similar memories to keep your knowledge base clean
- **Export/Import**: backup and transfer memory databases

## Installation

```bash
# From PyPI
pip install sqler-cli

# From source
cd sqler-cli
uv sync
uv run mem --help

# Or install globally
uv pip install -e .
```

## Quick Start

```bash
# Store memories
mem remember "The API key is stored in .env file"
mem remember "User prefers dark mode and vim keybindings" --tag preferences
mem remember "POST /api/v1/users creates a new user" --tag api --tag docs

# Search memories (full-text search)
mem recall "API key"              # Finds the .env memory
mem recall "user" --tag api       # Finds only API-related user memories

# List all memories
mem list
mem list --tag preferences        # Filter by tag

# Get JSON output (for scripts/LLMs)
mem recall "preferences" --json

# Check what's stored
mem stats
```

## Commands Reference

### remember - Store a memory

```bash
mem remember "content to remember"
mem remember "content" --tag TAG [--tag TAG2 ...]
mem remember "content" --context "why this was stored"
mem remember "content" --source claude  # default: user
mem remember --file notes.txt           # read from file
echo "content" | mem remember           # read from stdin

# Session isolation - group related memories
mem remember "Auth refactor notes" --session auth-refactor

# Auto-tagging - detect tags from content (api, database, auth, config, error, security)
mem remember "JWT authentication setup" --auto-tag
# Output: Remembered (id=1) [auto-tagged: auth, security]

# Memory linking
mem remember "New API URL is /v2" --supersedes 42        # Replaces old memory
mem remember "Login flow" --see-also 15 --see-also 23   # Links related memories

# Source attribution
mem remember "Rate limit is 100/min" --source-url "https://api.example.com/docs"
mem remember "Config format" --source-file "/etc/app/config.yaml:42"

# Importance (1-5, default 3)
mem remember "CRITICAL: Never commit secrets" --importance 5

# Output formats
mem remember "content" --json    # {"id": 1, "content": "...", "tags": [], "auto_tags": [...]}
mem remember "content" --quiet   # just prints: 1
```

### recall - Search memories (FTS)

Full-text search using SQLite FTS5 with BM25 ranking.

```bash
mem recall "search query"
mem recall "query" --tag TAG           # filter by tag
mem recall "query" --limit 5           # max results (default: 10)
mem recall "query" --json              # JSON output for parsing

# Show relevance scores (useful for debugging search)
mem recall "query" --show-score        # adds score field to output

# Sort by date instead of relevance
mem recall "query" --recent-first      # newest first

# Session filtering
mem recall "query" --session auth-refactor  # only search this session

# Importance filtering
mem recall "query" --min-importance 4       # only important memories
mem recall "query" --boost-important        # prioritize high-importance in results
```

**Search syntax:**
- `mem recall "API endpoint"` - finds memories containing both words
- `mem recall "sqlite OR postgres"` - boolean OR
- `mem recall "config*"` - prefix matching

### update - Modify a memory in-place

Update content, tags, or metadata without losing the memory ID or creation timestamp.

```bash
mem update 42 "New content"              # Replace content
mem update 42 --tag newtag               # Add a tag
mem update 42 --context "New context"    # Update context
mem update 42 --clear-tags               # Remove all tags
mem update 42 --importance 5             # Mark as critical
mem update 42 --see-also 15 --see-also 23  # Add related memories
mem update 42 --session new-session      # Change session
```

### list - Browse memories

```bash
mem list                       # all memories
mem list --tag preferences     # filter by tag
mem list --limit 20            # limit results
mem list --since 2024-01-01    # filter by date
mem list --session auth-work   # filter by session
mem list --min-importance 4    # only important memories
mem list --json                # JSON output
```

### forget - Delete memories

```bash
mem forget 42                         # delete by ID
mem forget --tag temporary --confirm  # bulk delete by tag
```

### tags - Manage tags

```bash
mem tags list              # show all tags with counts
mem tags add 42 important  # add tag to memory
mem tags rm 42 draft       # remove tag from memory
```

### dedupe - Find and merge duplicates

Find near-duplicate memories and optionally merge them.

```bash
mem dedupe              # Interactive: show groups, ask which to merge
mem dedupe --dry-run    # Just show duplicates without action
mem dedupe --auto       # Auto-merge keeping newest content

# Adjust similarity threshold (lower = more similar required)
mem dedupe --threshold -3.0
```

When merging:
- Tags from all duplicates are combined
- Newest content is kept
- Older memories are deleted

### Database management

```bash
mem init                   # initialize DB (auto on first use)
mem stats                  # show counts and DB size
mem stats --json           # JSON format
mem export backup.json     # export all memories
mem import backup.json     # import from file
mem rebuild-index          # rebuild FTS index (maintenance/recovery)
```

## Global Options

| Option | Description |
|--------|-------------|
| `--db PATH` | Override database path (default: `.sqler-cli/memory.db`) |
| `--json` | Output as JSON (for scripts/LLMs) |
| `--quiet` | Minimal output (IDs only) |

Environment variable: `SQLER_CLI_DB` sets default database path.

## Output Formats

**Default** - Human-readable tables:
```
┏━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┓
┃ ID   ┃ Content                     ┃ Tags         ┃ Created        ┃
┡━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━┩
│ 1    │ API key is in .env          │ config       │ 2024-01-15 10:30│
│ 2    │ User prefers dark mode      │ preferences  │ 2024-01-15 10:32│
└──────┴─────────────────────────────┴──────────────┴────────────────┘
```

**JSON** (`--json`) - For programmatic access:
```json
[
  {
    "id": 1,
    "content": "API key is in .env",
    "tags": ["config"],
    "context": null,
    "source": "user",
    "session_id": null,
    "supersedes": null,
    "see_also": [],
    "source_url": null,
    "source_file": null,
    "importance": 3,
    "created_at": "2024-01-15T10:30:00+00:00",
    "updated_at": "2024-01-15T10:30:00+00:00"
  }
]
```

With `--show-score`:
```json
[
  {
    "id": 1,
    "content": "API key is in .env",
    "score": -2.45,
    ...
  }
]
```

**Quiet** (`--quiet`) - Just IDs:
```
1
2
3
```

## Data Model

Each memory has:

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Auto-assigned unique identifier |
| `content` | string | The thing to remember (required, searchable) |
| `tags` | string[] | Categories for filtering |
| `context` | string | Why/where this was stored (searchable) |
| `source` | string | Who created it: "user", "claude", "file", etc. |
| `session_id` | string | Session for grouping related memories |
| `supersedes` | int | ID of memory this replaces |
| `see_also` | int[] | IDs of related memories |
| `source_url` | string | URL where info came from |
| `source_file` | string | File path where info came from |
| `importance` | int | Priority 1-5 (default: 3) |
| `created_at` | datetime | When created |
| `updated_at` | datetime | When last modified |

## Example Workflows

### Session handoff
```bash
# End of session - save context
mem remember "Working on auth module, JWT refresh logic incomplete" \
  --tag session --session 2024-01-15-auth --importance 4

# New session - recall context
mem recall "session" --session 2024-01-15-auth
mem list --session 2024-01-15-auth
```

### Project conventions
```bash
# Store project rules with auto-tagging
mem remember "Use snake_case for Python, camelCase for TypeScript" --tag conventions
mem remember "All API responses use {data, error, meta} envelope" --auto-tag --tag conventions

# Later, recall them
mem recall "conventions" --tag api
```

### Decision log with linking
```bash
# Record initial decision
mem remember "Chose PostgreSQL over MySQL for JSON support" \
  --tag decisions --context "Database selection meeting"
# Returns: Remembered (id=42)

# Later, update the decision
mem remember "Switched to SQLite for simpler deployment" \
  --tag decisions --supersedes 42

# View with context
mem list --tag decisions --json  # Shows supersedes chain
```

### Knowledge cleanup
```bash
# Find and review duplicates
mem dedupe --dry-run

# Auto-merge obvious duplicates
mem dedupe --auto

# Or interactively choose
mem dedupe
```

### Importance-based filtering
```bash
# Mark critical info
mem remember "NEVER commit .env files" --importance 5 --tag security

# Quick recall of important stuff only
mem recall "security" --min-importance 4
mem list --min-importance 4
```

## Database Location

Priority order:
1. `--db PATH` flag (explicit override)
2. `SQLER_CLI_DB` environment variable
3. `--global` flag → forces `~/.sqler-cli/memory.db`
4. Local `.sqler-cli/` exists in CWD → uses local
5. Fallback → global `~/.sqler-cli/memory.db`

**Global by default**: Run `mem` from anywhere and it uses `~/.sqler-cli/memory.db`.

**Project-local opt-in**: Run `mem init` in a project to create a local `.sqler-cli/` directory. After that, commands in that directory use the local DB.

**Force global**: Use `--global` (or `-g`) to skip local detection and use global DB.

```bash
# From anywhere - uses global ~/.sqler-cli/
mem remember "Shared across all sessions"

# Create project-local DB
cd ~/projects/my-app
mem init                    # Creates .sqler-cli/ here
mem remember "Project-specific note"  # Goes to local DB

# Force global even when local exists
mem remember "Still global" --global
mem list --global
```

## Tips for LLMs

1. **Always use `--json`** for reliable parsing
2. **Use `--quiet`** when you only need IDs for chaining
3. **Tag consistently** - use the same tags across sessions
4. **Use sessions** - isolate memories by conversation/task with `--session`
5. **Auto-tag** - let the CLI detect common categories with `--auto-tag`
6. **Link memories** - use `--supersedes` when updating info, `--see-also` for related
7. **Mark importance** - use `--importance 5` for critical info, filter with `--min-importance`
8. **Search is fuzzy** - FTS5 handles stemming (e.g., "running" matches "run")
9. **Context helps recall** - store why you remembered something
10. **Source tracking** - use `--source claude` to track AI-generated memories
11. **Check for similar** - after remember, similar memories are shown to help avoid duplicates
12. **Periodic cleanup** - run `mem dedupe --dry-run` to find duplicates

## Auto-Tag Categories

When using `--auto-tag`, the CLI detects these categories from content:

| Tag | Detected Keywords |
|-----|-------------------|
| `api` | api, endpoint, rest, graphql, http |
| `database` | database, db, sql, postgres, sqlite, mongo |
| `config` | config, configuration, settings, .env, environment |
| `auth` | auth, authentication, jwt, oauth, password, login |
| `error` | error, exception, bug, fix, issue |
| `security` | security, secret, key, credential, token |
