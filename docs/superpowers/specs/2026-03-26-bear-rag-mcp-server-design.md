# Bear Notes MCP Server — Design Spec

## Overview

An MCP (Model Context Protocol) server that exposes Bear notes to Claude Code as searchable tools. Gives Claude Code the same multi-strategy exploration capability over notes that it has over codebases — semantic search, structured browsing, full-text retrieval, and metadata filtering.

Built as a thin query layer over the existing `bear-rag` modules. No new data stores, no duplication of logic.

## Principles

* **Local-only.** The MCP server runs as a local subprocess over stdio. No network transport, no HTTP, no ports. Data never leaves the machine through this server.
* **Read-only.** Bear SQLite access is strictly read-only (`?mode=ro` URI). The MCP server cannot modify Bear data.
* **Reuse existing modules.** The server imports and delegates to `BearReader`, `NoteStore`, `Retriever`, and `sync` directly.
* **Claude Code is the LLM.** The server returns raw data. No answer generation — Claude Code reasons over the results itself.

## Security Constraints

* **stdio transport only.** The MCP server MUST use stdio transport. It MUST NOT expose HTTP, SSE, WebSocket, or any network-accessible transport. This ensures the server is only reachable by the local Claude Code process that spawned it.
* **Read-only Bear DB.** All SQLite connections use `?mode=ro` URI parameter, enforced at the connection level. No write operations against Bear's database are permitted.
* **No secrets in transit.** The MCP server does not require or handle API keys. It has no access to `ANTHROPIC_API_KEY` — that's only used by the `ask` CLI command.
* **No data exfiltration path.** The server has no network capabilities. It reads local SQLite and local ChromaDB, and returns results over stdio to the parent process.

## Architecture

```
Claude Code
    ↕ (MCP protocol over stdio — local only)
bear-rag-mcp (subprocess)
    ├── search_notes  →  NoteStore.query() (ChromaDB vector search)
    ├── read_note     →  BearReader (SQLite, read-only)
    ├── list_notes    →  BearReader (SQLite, read-only)
    ├── list_tags     →  BearReader (SQLite, read-only)
    └── sync_notes    →  sync.sync()
```

The MCP server is a separate entry point from the CLI. They share all modules but run independently.

## MCP Tools

### `search_notes`

Semantic vector search over ChromaDB. The primary discovery tool — finds content by meaning regardless of titles or tags.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | `str` | yes | — | Natural language search string |
| `tags` | `list[str]` | no | `None` | Filter results to notes with any of these tags |
| `limit` | `int` | no | `10` | Maximum results to return |

**Returns:** List of objects:
```json
{
  "title": "Note title",
  "text": "Chunk text content...",
  "tags": "tag1,tag2",
  "heading_path": "## Section > ### Subsection",
  "note_pk": 42,
  "chunk_index": 0,
  "modified_at": "2026-03-25T12:00:00+00:00"
}
```

**Implementation:** Delegates to `NoteStore.query()`. Tag filtering uses ChromaDB's native `where` clause on chunk metadata. When `tags` is provided, constructs a `where` filter like `{"tags": {"$contains": tag}}` for single tags, or an `$or` filter for multiple tags.

### `read_note`

Fetch the full text of a specific note from Bear DB. Used after `search_notes` to get complete context when a chunk isn't enough.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `title` | `str` | yes | — | Note title (case-insensitive match) |

**Returns:** Single object:
```json
{
  "title": "Exact Title",
  "text": "Full markdown content...",
  "tags": ["tag1", "tag2"],
  "modified_at": "2026-03-25T12:00:00+00:00"
}
```

Returns an error message if no note matches the title.

**Implementation:** New `BearReader.read_note_by_title(title)` method. Uses `WHERE LOWER(ZTITLE) = LOWER(?)` for case-insensitive matching.

### `list_notes`

Browse and filter notes by metadata. All parameters optional — calling with no parameters returns the most recent notes.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tag` | `str` | no | `None` | Filter to notes with this tag |
| `modified_since` | `str` | no | `None` | ISO date string (e.g. `"2026-01-01"`) |
| `modified_before` | `str` | no | `None` | ISO date string |
| `title_contains` | `str` | no | `None` | Substring match on title (case-insensitive) |
| `limit` | `int` | no | `50` | Maximum results |

**Returns:** List of metadata objects (no full text — keeps responses compact):
```json
{
  "title": "Note title",
  "tags": ["tag1", "tag2"],
  "modified_at": "2026-03-25T12:00:00+00:00",
  "note_pk": 42
}
```

**Implementation:** New `BearReader.list_notes(...)` method. Builds a dynamic SQL query with optional `WHERE` clauses. Date parameters are converted from ISO strings to Core Data timestamps for the query.

### `list_tags`

List all tags with note counts. Orientation tool — helps Claude discover what's in the collection before drilling down.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|

No parameters.

**Returns:** List of objects sorted by count descending:
```json
{
  "tag": "project/foo",
  "count": 15
}
```

**Implementation:** New `BearReader.list_tags()` method. Simple `SELECT ZTITLE, COUNT(*) ... GROUP BY` on the tag join table, filtering to non-trashed notes.

### `sync_notes`

Trigger an incremental sync from Bear DB to ChromaDB. For mid-session refresh when notes have been edited in Bear.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|

No parameters.

**Returns:**
```json
{
  "notes_updated": 3,
  "notes_deleted": 0,
  "chunks_indexed": 12
}
```

**Implementation:** Calls `sync.sync()` directly with default parameters.

## New BearReader Methods

Three new methods added to the existing `BearReader` class:

### `read_note_by_title(title: str) -> BearNote | None`

Case-insensitive title lookup. Returns `None` if no match found.

```sql
SELECT n.Z_PK, n.ZTITLE, n.ZTEXT, n.ZMODIFICATIONDATE, n.ZTRASHED, n.ZARCHIVED
FROM ZSFNOTE n
WHERE LOWER(n.ZTITLE) = LOWER(?) AND n.ZTRASHED = 0
```

### `list_notes(tag?, modified_since?, modified_before?, title_contains?, limit?) -> list[BearNote]`

Filtered metadata query. Builds SQL dynamically based on which parameters are provided. Date parameters arrive as ISO strings and are converted to Core Data timestamps. Returns `BearNote` objects (full text included in the model but the MCP tool handler strips it from the response to keep things compact).

### `list_tags() -> list[tuple[str, int]]`

Returns `(tag_name, count)` tuples sorted by count descending. Only counts non-trashed notes.

```sql
SELECT t.ZTITLE, COUNT(*) as cnt
FROM ZSFNOTETAG t
JOIN Z_5TAGS jt ON jt.Z_13TAGS = t.Z_PK
JOIN ZSFNOTE n ON n.Z_PK = jt.Z_5NOTES
WHERE n.ZTRASHED = 0
GROUP BY t.ZTITLE
ORDER BY cnt DESC
```

## MCP Server Module

One new file: `bear_rag/mcp_server.py`

Uses the `mcp` Python SDK (FastMCP) for protocol handling. The server is thin — each tool handler is 10-20 lines delegating to existing modules.

```python
# Structure (pseudocode)
from mcp.server.fastmcp import FastMCP

server = FastMCP("bear-notes", description="Search and browse Bear.app notes")

@server.tool()
def search_notes(query: str, tags: list[str] | None = None, limit: int = 10) -> list[dict]:
    """Semantic search over Bear notes. Returns relevant chunks ranked by similarity."""
    ...

@server.tool()
def read_note(title: str) -> dict:
    """Get the full text of a specific Bear note by title."""
    ...

@server.tool()
def list_notes(tag: str | None = None, ...) -> list[dict]:
    """Browse and filter notes by tag, date range, or title."""
    ...

@server.tool()
def list_tags() -> list[dict]:
    """List all tags with note counts."""
    ...

@server.tool()
def sync_notes() -> dict:
    """Sync recent Bear note changes into the search index."""
    ...

def main():
    server.run(transport="stdio")
```

Tool descriptions are important — Claude Code reads them to decide when to use each tool. They should be clear about what each tool does and when to use it.

## Entry Point

New console script in `pyproject.toml`:

```toml
[project.scripts]
bear-rag = "bear_rag.cli:main"
bear-rag-mcp = "bear_rag.mcp_server:main"
```

## New Dependency

```toml
dependencies = [
    "anthropic>=0.49,<1.0",
    "chromadb>=1.0,<2.0",
    "mcp>=1.0,<2.0",
    "python-dotenv>=1.0,<2.0",
]
```

The `mcp` package is the official MCP Python SDK. It handles stdio transport, JSON-RPC protocol, tool registration, and schema generation.

## CLI Changes

### `--quiet` flag for sync

Add `--quiet` flag to the `sync` subcommand. When set, suppresses output if there are zero changes. Used by the pre-session hook to avoid noise.

```
bear-rag sync --quiet    # prints nothing if no changes
bear-rag sync --quiet    # prints "Synced 3 notes (12 chunks)" if there are changes
```

## Claude Code Configuration

### Pre-session Hook

Runs `bear-rag sync` when Claude Code starts a session. Configured in Claude Code settings:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "command": "cd /Users/adamboulware/Docker/bear-app-rag && uv run bear-rag sync --quiet",
        "timeout": 30000
      }
    ]
  }
}
```

### MCP Server Registration

In Claude Code settings (`~/.claude/settings.json` or project-level):

```json
{
  "mcpServers": {
    "bear-notes": {
      "command": "uv",
      "args": ["run", "--directory", "/Users/adamboulware/Docker/bear-app-rag", "bear-rag-mcp"]
    }
  }
}
```

### CLAUDE.md Hint

Add to global `~/.claude/CLAUDE.md`:

```
When I ask about my notes, Bear notes, or reference personal knowledge,
use the bear-notes MCP tools. Use multiple search strategies (tags,
semantic search, browsing) to be thorough.
```

## Testing

### New Tests

* **`test_mcp_server.py`** — Tests MCP tool handlers by calling them as functions directly. No MCP protocol testing (that's the SDK's job).
  * `search_notes`: vector search returns expected chunks, tag filtering works, limit respected
  * `read_note`: finds note by title case-insensitively, returns None for missing
  * `list_notes`: filters by tag, date range, title substring
  * `list_tags`: returns all tags with correct counts
  * `sync_notes`: delegates to sync and returns result

* **`test_bear_reader.py`** — Extended with tests for the three new methods:
  * `read_note_by_title`: case-insensitive match, returns None for missing
  * `list_notes`: all filter combinations
  * `list_tags`: counts match expected data

### Existing Tests

All existing tests continue to pass unchanged. The new code is additive — no modifications to existing module interfaces.

## What We're NOT Building

* **No answer generation** — Claude Code is the LLM
* **No caching layer** — ChromaDB and SQLite are fast enough at this scale
* **No authentication** — local stdio, no network surface
* **No web UI** — Claude Code is the UI
* **No write operations to Bear** — strictly read-only
* **No conversation state in the MCP server** — Claude Code manages context
* **No custom embeddings** — ChromaDB's built-in ONNX embeddings
* **No network transport** — stdio only, local only, always

## Project Structure (After)

```
bear-rag/
├── bear_rag/
│   ├── __init__.py
│   ├── config.py
│   ├── bear_reader.py      # + 3 new methods
│   ├── chunker.py
│   ├── store.py
│   ├── retriever.py
│   ├── generator.py
│   ├── sync.py
│   ├── models.py
│   ├── cli.py               # + --quiet flag on sync
│   └── mcp_server.py        # NEW — MCP server entry point
├── tests/
│   ├── conftest.py
│   ├── test_bear_reader.py   # + tests for new methods
│   ├── test_chunker.py
│   ├── test_store.py
│   ├── test_retriever.py
│   ├── test_sync.py
│   ├── test_generator.py
│   ├── test_cli.py
│   └── test_mcp_server.py   # NEW
├── pyproject.toml            # + mcp dependency, + bear-rag-mcp entry point
└── ...
```
