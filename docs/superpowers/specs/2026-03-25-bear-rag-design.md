# Bear Notes RAG System — Design Spec

## Overview

A local-first retrieval-augmented generation (RAG) pipeline that indexes Bear app notes into a vector store and serves answers via Claude. Designed for stability, minimal dependencies, and low operational overhead.

## Principles

* **Stable over shiny.** Every dependency has 2+ years of production track record.
* **Local-first.** Embeddings run locally via ONNX. No data leaves the machine unless you explicitly query Claude.
* **Incremental by default.** Only re-indexes changed notes. Full rebuilds available but never required.
* **Simple orchestration.** A cron job and a Python script.

## Deviations from Original Plan

This spec supersedes `bear-rag-plan.md`. Key changes:

| Change                                                       | Rationale                                                                                                                                         |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Removed `embedder.py` and `sentence-transformers` dependency | ChromaDB's built-in ONNX embedding function uses the same model (`all-MiniLM-L6-v2`) without pulling in PyTorch (\~2GB).                          |
| Removed `index.py`, absorbed into `sync.py`                  | `index` is just `reset() + sync from timestamp 0`. One write codepath, not two.                                                                   |
| Added `python-dotenv` dependency                             | Loads `ANTHROPIC_API_KEY` from `.env` file for portability.                                                                                       |
| Added `config.py` module                                     | Centralizes constants (paths, model name, chunk sizes) instead of scattering them.                                                                |
| ChromaDB version `>=1.0,<2.0` (plan had `>=0.5,<1.0`)        | ChromaDB 1.0 is the current stable release.                                                                                                       |
| Anthropic SDK version `>=0.49,<1.0` (plan had `>=0.40,<1.0`) | Targets current stable release.                                                                                                                   |
| Added `.python-version` file                                 | For `uv` to auto-select the right Python. Value is `3.14` (the user's active version); `requires-python >= 3.11` remains the compatibility floor. |
| `uv` as project tooling (plan did not specify)               | Modern, fast, handles venvs + deps + lockfiles.                                                                                                   |
| `pytest` as test framework (plan did not specify)            | De facto standard, added as dev dependency.                                                                                                       |

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────────────────┐
│  Bear SQLite  │────▶│   Chunker    │────▶│          ChromaDB            │
│  (read-only)  │     │  (heading +  │     │  (embed via ONNX + persist)  │
│               │     │   fallback)  │     │                              │
└──────────────┘     └──────────────┘     └──────────────────────────────┘
                                                         │
                                                         ▼
                                                 ┌──────────────┐
                                                 │  Claude API  │
                                                 │  (retrieval  │
                                                 │   + answer)  │
                                                 └──────────────┘
```

ChromaDB handles both vector storage and embedding (via its default `all-MiniLM-L6-v2` ONNX embedding function). There is no separate embedding module.

## Project Structure

```
bear-rag/
├── bear_rag/
│   ├── __init__.py
│   ├── config.py              # Constants and paths
│   ├── bear_reader.py         # SQLite extraction
│   ├── chunker.py             # Markdown-aware splitting
│   ├── store.py               # ChromaDB operations (embedding happens here)
│   ├── retriever.py           # Query → chunks
│   ├── generator.py           # Chunks → Claude answer
│   ├── sync.py                # Incremental sync logic
│   ├── models.py              # Dataclasses
│   └── cli.py                 # argparse entry point
├── tests/
│   ├── conftest.py            # Shared fixtures (test DB, test ChromaDB collection)
│   ├── test_chunker.py
│   ├── test_bear_reader.py
│   ├── test_store.py
│   ├── test_retriever.py
│   ├── test_sync.py
│   └── test_generator.py
├── pyproject.toml
├── README.md
├── .env                       # ANTHROPIC_API_KEY only
├── .gitignore
└── .python-version            # 3.14
```

## Dependencies

```TOML
[project]
name = "bear-rag"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.49,<1.0",
    "chromadb>=1.0,<2.0",
    "python-dotenv>=1.0,<2.0",
]

[project.optional-dependencies]
dev = ["pytest>=9.0,<10.0"]

[project.scripts]
bear-rag = "bear_rag.cli:main"
```

Tooling: `uv` for project management, virtual environments, and dependency resolution.

## Data Model

### BearNote (dataclass)

| Field         | Type        | Description                        |
| ------------- | ----------- | ---------------------------------- |
| `pk`          | `int`       | Primary key from Bear DB           |
| `title`       | `str`       | Note title                         |
| `text`        | `str`       | Full Markdown content              |
| `modified_at` | `datetime`  | Converted from Core Data timestamp |
| `tags`        | `list[str]` | Tags from join table               |
| `is_trashed`  | `bool`      | Whether note is trashed            |
| `is_archived` | `bool`      | Whether note is archived           |

### ChunkMetadata (TypedDict)

| Key            | Type  | Description                                                              |
| -------------- | ----- | ------------------------------------------------------------------------ |
| `note_pk`      | `int` | Source note PK                                                           |
| `title`        | `str` | Note title                                                               |
| `tags`         | `str` | Comma-separated tag list (converted from `BearNote.tags` by the chunker) |
| `chunk_index`  | `int` | Position within the note                                                 |
| `heading_path` | `str` | Heading hierarchy, e.g. `"## Setup > ### Config"`                        |
| `modified_at`  | `str` | ISO 8601 timestamp                                                       |
| `source`       | `str` | Always `"bear"`                                                          |

### Chunk (dataclass)

| Field      | Type            | Description                       |
| ---------- | --------------- | --------------------------------- |
| `id`       | `str`           | Format: `{note_pk}_{chunk_index}` |
| `text`     | `str`           | Chunk content                     |
| `metadata` | `ChunkMetadata` | Typed metadata dict (see above)   |

## Config

### config.py — Constants and Paths

Centralizes all configuration so nothing is hardcoded across modules.

```Python
from pathlib import Path

# Bear database
BEAR_DB_PATH = Path.home() / "Library/Group Containers/9K33E3U3T4.net.shinyfrog.bear/Application Data/database.sqlite"

# Persistent state
DATA_DIR = Path.home() / ".bear-rag"
CHROMA_DIR = DATA_DIR / "chroma"
SYNC_STATE_PATH = DATA_DIR / "last_sync.json"

# Chunking
MAX_CHUNK_WORDS = 300       # ~390 tokens; longer chunks may be truncated during embedding (see note below)
MIN_CHUNK_WORDS = 30        # Below this, merge into preceding chunk
OVERLAP_WORDS = 40          # Overlap when splitting oversized chunks at paragraph boundaries

# Claude
CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_MAX_TOKENS = 4096
```

**Note on chunk sizing:** `all-MiniLM-L6-v2` has a max sequence length of 256 tokens. Text beyond that is truncated during embedding. We use word count as a proxy (\~1.3 tokens per word). `MAX_CHUNK_WORDS = 300` (\~390 tokens) intentionally exceeds the 256-token embedding window — we prioritize semantic coherence (splitting at heading/paragraph boundaries) over strict token limits. The embedding captures the first \~256 tokens, which is usually enough for retrieval relevance. The full chunk text is stored in ChromaDB and passed to Claude for generation, so no content is lost. This is more conservative than the original plan's 500-token limit (reduced from plan's 500 tokens, plan's 50-token overlap → 40 words, plan's 50-token merge threshold → 30 words).

## Component Design

### bear\_reader.py — SQLite Extraction

* Opens Bear DB at `config.BEAR_DB_PATH` in **read-only mode** (`?mode=ro` URI).
* All SQLite access lives in this module.
* On init, **validates the DB file exists** and raises a clear `FileNotFoundError` with a user-facing message if not found (e.g., "Bear database not found at {path}. Is Bear installed?").

**Interface:**

* `read_notes(include_archived=False) -> list[BearNote]` — reads all non-trashed notes with tags via join.
* `read_notes_modified_since(timestamp: float) -> list[BearNote]` — notes modified after the given Core Data timestamp. Used by sync.
* `read_trashed_pks() -> list[int]` — returns PKs of trashed notes. Used by sync to clean up the index.

**Implementation notes:**

* Joins `ZSFNOTE` → join table → `ZSFNOTETAG` to get tags in one query.
* Core Data timestamps (seconds since 2001-01-01) are converted to Python `datetime`.
* Join table column names (`Z_7NOTES`, `Z_14TAGS` per original plan) **must be validated** against the actual Bear DB schema before hardcoding — these are Core Data auto-generated names that can vary between Bear versions.

### chunker.py — Markdown-Aware Splitting

Takes a `BearNote`, returns an ordered `list[Chunk]` with metadata populated. Converts `BearNote.tags` (list) to comma-separated string for `ChunkMetadata.tags`.

**Interface:**

```Python
def chunk_note(note: BearNote) -> list[Chunk]
```

**Algorithm:**

1. **Primary split:** Regex on `^#{1,6} `  at line boundaries. Each chunk inherits a `heading_path` tracking the heading hierarchy.
2. **Code block awareness:** Track fenced code blocks (` ``` `). Ignore `#` characters inside code blocks to prevent false splits.
3. **Secondary split:** Chunks exceeding `MAX_CHUNK_WORDS` words are split at paragraph boundaries (double newline) with `OVERLAP_WORDS` overlap.
4. **Merge-up:** Chunks under `MIN_CHUNK_WORDS` words merge into the preceding chunk. **Edge cases:** if the first chunk is undersized, merge it forward into the next chunk. If all chunks in a note are undersized, concatenate them into a single chunk.

### store.py — ChromaDB Operations

Class-based module that manages the `"bear_notes"` ChromaDB collection. ChromaDB's default embedding function (`all-MiniLM-L6-v2` via ONNX, 384 dimensions) handles embedding automatically on `add()` and `query()`.

**Interface:**

```Python
class NoteStore:
    def __init__(self, persist_dir: Path = config.CHROMA_DIR):
        """Initialize ChromaDB persistent client and get/create the collection."""

    def upsert_chunks(self, chunks: list[Chunk]) -> None:
        """Idempotent upsert by chunk ID. Batches in groups of ~100."""

    def delete_note(self, note_pk: int) -> None:
        """Remove all chunks for a note using ChromaDB where filter on note_pk."""

    def query(self, text: str, n_results: int = 5) -> list[Chunk]:
        """Embed query text and return top-k matching chunks.
        Reconstructs Chunk objects from ChromaDB's raw response format
        (parallel lists of documents, metadatas, distances, ids)."""

    def get_stats(self) -> dict:
        """Return collection count and metadata for the status subcommand."""

    def reset(self) -> None:
        """Delete and recreate the collection. Used by index for full rebuilds."""
```

The `persist_dir` parameter defaults to `config.CHROMA_DIR` but can be overridden in tests (e.g., with a temp directory).

### retriever.py — Query Interface

Thin layer that takes a question and returns relevant chunks. Uses a `NoteStore` instance for the actual query.

**Interface:**

```Python
class Retriever:
    def __init__(self, store: NoteStore):
        """Takes a NoteStore instance."""

    def retrieve(self, question: str, n_results: int = 5) -> list[Chunk]:
        """Embed the question via store.query() and return matching chunks."""
```

Separated from `store.py` to keep read and write concerns distinct. The `NoteStore` is injected, making both classes independently testable.

### generator.py — Claude Integration

Uses the Anthropic Python SDK. API key read from `ANTHROPIC_API_KEY` env var (loaded from `.env` via python-dotenv at CLI startup).

**Interface:**

```Python
def generate_answer(question: str, chunks: list[Chunk]) -> str
```

**Behavior:**

* If no chunks provided, returns a "no relevant notes found" message without calling the API.
* Model: `config.CLAUDE_MODEL`
* `max_tokens`: `config.CLAUDE_MAX_TOKENS` (4096)
* `temperature`: `1` (default — no override needed)
* No retry logic in v1. API errors propagate to the caller with the SDK's error messages.

**API key validation:** The `ask` subcommand checks for `ANTHROPIC_API_KEY` at startup and fails with a clear message if missing. The `index`, `sync`, and `status` subcommands do **not** require the API key and work without it.

**Prompt template:**

```
You are a knowledge assistant grounded in the user's personal notes.
Answer based ONLY on the provided context. Cite the chunk number [1], [2], etc.
If the context doesn't contain enough information, say so explicitly.

## Retrieved Context

{for each chunk}
[{i}] (Source: {title} > {heading_path} | Tags: {tags} | Modified: {modified_at})
{chunk_text}
{/for}

## Question
{user_question}
```

### sync.py — Incremental Sync

**Interface:**

```Python
@dataclass
class SyncResult:
    notes_updated: int
    notes_deleted: int
    chunks_added: int

def sync(store: NoteStore, dry_run: bool = False) -> SyncResult:
    """Run an incremental sync. If dry_run=True, compute changes but don't modify the store or state file."""

def full_index(store: NoteStore) -> SyncResult:
    """Reset the store and run a full sync from timestamp 0."""
```

**State file:** `config.SYNC_STATE_PATH` (`~/.bear-rag/last_sync.json`)

```JSON
{"timestamp": 0.0, "synced_at": "2026-03-25T12:00:00"}
```

`timestamp` is always a float (Core Data timestamp). Default is `0.0` if the state file doesn't exist.

**Flow:**

1. Read last sync timestamp from state file (or `0.0` if first run).
2. Call `bear_reader.read_notes_modified_since(timestamp)` for changed notes.
3. Call `bear_reader.read_trashed_pks()` for deletions.
4. If `dry_run`: print what would change, return `SyncResult` without modifying anything.
5. For each changed note: delete old chunks from store, re-chunk, upsert.
6. For trashed notes: delete from store.
7. Write new timestamp to state file **only on success**.

**Design decision:** `full_index()` calls `store.reset()` then `sync()` with timestamp `0.0`. One write codepath, not two.

### cli.py — Entry Point

Uses `argparse` with subcommands. Loads `.env` via `python-dotenv` at the top of `main()` before any other initialization.

| Subcommand                | Description                             |
| ------------------------- | --------------------------------------- |
| `bear-rag index`          | Full rebuild (reset + sync from zero)   |
| `bear-rag sync`           | Incremental update since last sync      |
| `bear-rag sync --dry-run` | Print what would change, don't modify   |
| `bear-rag ask "question"` | One-shot query + answer                 |
| `bear-rag ask`            | Interactive REPL mode                   |
| `bear-rag status`         | Last sync time, chunk count, note count |

**Wiring:** `main()` parses args, loads `.env`, creates `NoteStore`, and dispatches to the appropriate module based on subcommand. Only `ask` creates an Anthropic client (and checks for `ANTHROPIC_API_KEY`).

**REPL mode:** When `bear-rag ask` is invoked with no question argument, enters a loop that reads questions from stdin. Each query is independent (no conversation history — multi-turn is out of scope). Exit via `Ctrl+D` (EOF) or typing `exit`/`quit`.

Entry point registered in `pyproject.toml` as `bear-rag = "bear_rag.cli:main"`.

## Error Handling

| Scenario                               | Behavior                                                                                                                                                  |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Bear DB not found                      | `bear_reader` raises `FileNotFoundError` with path and "Is Bear installed?" message                                                                       |
| Bear DB empty (zero non-trashed notes) | `sync`/`index` complete successfully with `SyncResult(0, 0, 0)` and print "No notes found"                                                                |
| `ANTHROPIC_API_KEY` not set            | `ask` subcommand fails at startup with clear message. Other subcommands work without it.                                                                  |
| ChromaDB directory corrupted           | `bear-rag index` (full rebuild) recovers by deleting and recreating the collection. For `sync`, error propagates with suggestion to run `bear-rag index`. |
| Claude API errors                      | No retries in v1. SDK errors propagate to the user with their original messages.                                                                          |
| `~/.bear-rag/` doesn't exist           | Created automatically on first run by any subcommand.                                                                                                     |

## Persistent State

All persistent state lives under `~/.bear-rag/`:

| Path                         | Purpose                     |
| ---------------------------- | --------------------------- |
| `~/.bear-rag/chroma/`        | ChromaDB persistent storage |
| `~/.bear-rag/last_sync.json` | Sync timestamp state        |
| `~/.bear-rag/sync.log`       | Cron sync log output        |

Path defined once in `config.py` as `DATA_DIR`.

## Cron Setup

```
*/15 * * * * cd /path/to/bear-rag && uv run bear-rag sync >> ~/.bear-rag/sync.log 2>&1
```

## Testing Strategy

* **Framework:** pytest
* **Shared fixtures (`conftest.py`):** Test SQLite database (Bear schema with synthetic data), ephemeral ChromaDB collection (in-memory or temp directory).
* **`test_chunker.py`:** Edge cases — no headings, single heading, deeply nested, code blocks containing `#`, chunks that need secondary splitting, chunks that need merge-up, first-chunk-undersized, all-chunks-undersized.
* **`test_bear_reader.py`:** Uses the test SQLite fixture to avoid depending on the real Bear DB. Tests read, modified-since filtering, trashed note detection, and DB-not-found error.
* **`test_store.py`:** Upsert, delete by note\_pk, reset, get\_stats. Uses ephemeral ChromaDB.
* **`test_retriever.py`:** Integration test with a small ChromaDB collection and known documents, verifying that queries return expected results ranked correctly.
* **`test_sync.py`:** Incremental sync logic, dry-run behavior, state file read/write, full index via reset + sync.
* **`test_generator.py`:** Prompt construction from chunks, empty-chunk short-circuit (no API call). Does not test actual Claude API calls — mocks the Anthropic client.

## Future Considerations (Out of Scope)

* Hybrid search (vector + tag filtering)
* Cross-encoder reranking
* Multi-turn conversation in REPL
* Web UI
* Docker packaging
* Additional note sources (Obsidian, plain Markdown)

