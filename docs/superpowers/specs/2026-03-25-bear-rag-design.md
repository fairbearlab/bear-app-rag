# Bear Notes RAG System — Design Spec

## Overview

A local-first retrieval-augmented generation (RAG) pipeline that indexes Bear app notes into a vector store and serves answers via Claude. Designed for stability, minimal dependencies, and low operational overhead.

## Principles

- **Stable over shiny.** Every dependency has 2+ years of production track record.
- **Local-first.** Embeddings run locally via ONNX. No data leaves the machine unless you explicitly query Claude.
- **Incremental by default.** Only re-indexes changed notes. Full rebuilds available but never required.
- **Simple orchestration.** A cron job and a Python script.

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
│   ├── bear_reader.py      # SQLite extraction
│   ├── chunker.py           # Markdown-aware splitting
│   ├── store.py             # ChromaDB operations (embedding happens here)
│   ├── retriever.py         # Query → chunks
│   ├── generator.py         # Chunks → Claude answer
│   ├── sync.py              # Incremental sync logic
│   ├── models.py            # Dataclasses
│   └── cli.py               # argparse entry point
├── tests/
│   ├── conftest.py
│   ├── test_chunker.py
│   ├── test_bear_reader.py
│   └── test_retriever.py
├── pyproject.toml
├── .env                     # ANTHROPIC_API_KEY only
├── .gitignore
└── .python-version          # 3.14
```

## Dependencies

```toml
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
dev = ["pytest>=8.0,<9.0"]

[project.scripts]
bear-rag = "bear_rag.cli:main"
```

Tooling: `uv` for project management, virtual environments, and dependency resolution.

## Data Model

### BearNote (dataclass)

| Field         | Type           | Description                                      |
|---------------|----------------|--------------------------------------------------|
| `pk`          | `int`          | Primary key from Bear DB                         |
| `title`       | `str`          | Note title                                       |
| `text`        | `str`          | Full Markdown content                            |
| `modified_at` | `datetime`     | Converted from Core Data timestamp               |
| `tags`        | `list[str]`    | Tags from join table                             |
| `is_trashed`  | `bool`         | Whether note is trashed                          |
| `is_archived` | `bool`         | Whether note is archived                         |

### Chunk (dataclass)

| Field      | Type           | Description                                      |
|------------|----------------|--------------------------------------------------|
| `id`       | `str`          | Format: `{note_pk}_{chunk_index}`                |
| `text`     | `str`          | Chunk content                                    |
| `metadata` | `dict`         | See below                                        |

Chunk metadata:

| Key            | Type   | Description                              |
|----------------|--------|------------------------------------------|
| `note_pk`      | `int`  | Source note PK                           |
| `title`        | `str`  | Note title                               |
| `tags`         | `str`  | Comma-separated tag list                 |
| `chunk_index`  | `int`  | Position within the note                 |
| `heading_path` | `str`  | Heading hierarchy, e.g. `"## Setup > ### Config"` |
| `modified_at`  | `str`  | ISO 8601 timestamp                       |
| `source`       | `str`  | Always `"bear"`                          |

## Component Design

### bear_reader.py — SQLite Extraction

- Opens Bear DB at `~/Library/Group Containers/9K33E3U3T4.net.shinyfrog.bear/Application Data/database.sqlite` in **read-only mode** (`?mode=ro` URI).
- All SQLite access lives in this module.

**Interface:**

- `read_notes(include_archived=False) -> list[BearNote]` — reads all non-trashed notes with tags via join.
- `read_notes_modified_since(timestamp: float) -> list[BearNote]` — notes modified after the given Core Data timestamp. Used by sync.
- `read_trashed_pks() -> list[int]` — returns PKs of trashed notes. Used by sync to clean up the index.

**Implementation notes:**

- Joins `ZSFNOTE` → join table → `ZSFNOTETAG` to get tags in one query.
- Core Data timestamps (seconds since 2001-01-01) are converted to Python `datetime`.
- Join table column names (`Z_7NOTES`, `Z_14TAGS` per original plan) **must be validated** against the actual Bear DB schema before hardcoding — these are Core Data auto-generated names that can vary between Bear versions.

### chunker.py — Markdown-Aware Splitting

Takes a `BearNote`, returns an ordered `list[Chunk]` with metadata populated.

**Interface:**

```python
def chunk_note(note: BearNote) -> list[Chunk]
```

**Algorithm:**

1. **Primary split:** Regex on `^#{1,6} ` at line boundaries. Each chunk inherits a `heading_path` tracking the heading hierarchy.
2. **Code block awareness:** Track fenced code blocks (`` ``` ``). Ignore `#` characters inside code blocks to prevent false splits.
3. **Secondary split:** Chunks exceeding ~500 tokens (estimated via `len(text.split())`) are split at paragraph boundaries (double newline) with 50-token overlap.
4. **Merge-up:** Chunks under 50 tokens merge into the preceding sibling chunk. Simpler than tree-based parent merging; heading_path metadata still captures hierarchy.

### store.py — ChromaDB Operations

Manages the `"bear_notes"` ChromaDB collection. ChromaDB's default embedding function (`all-MiniLM-L6-v2` via ONNX, 384 dimensions) handles embedding automatically on `add()` and `query()`.

**Persistence:** `~/.bear-rag/chroma/`

**Interface:**

- `upsert_chunks(chunks: list[Chunk])` — idempotent by chunk ID. Batches in groups of ~100.
- `delete_note(note_pk: int)` — uses ChromaDB `where` filter on `note_pk` metadata.
- `get_stats() -> dict` — collection count and metadata for the `status` subcommand.
- `reset()` — deletes and recreates the collection. Used by `index` for full rebuilds.

### retriever.py — Query Interface

Thin layer over ChromaDB's query. Separated from `store.py` to keep read and write concerns distinct.

**Interface:**

```python
def retrieve(question: str, n_results: int = 5) -> list[Chunk]
```

Passes the question text to ChromaDB `query()` (embedded automatically), returns results as `Chunk` objects.

### generator.py — Claude Integration

Uses the Anthropic Python SDK. API key read from `ANTHROPIC_API_KEY` env var (loaded from `.env` via python-dotenv at CLI startup).

**Interface:**

```python
def generate_answer(question: str, chunks: list[Chunk]) -> str
```

**Behavior:**

- If no chunks provided, returns a "no relevant notes found" message without calling the API.
- Model: `claude-sonnet-4-20250514` (configurable constant).

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

**State file:** `~/.bear-rag/last_sync.json`

```json
{"timestamp": <Core Data float>, "synced_at": "<ISO 8601>"}
```

**Flow:**

1. Read last sync timestamp (or `0` if first run).
2. Call `bear_reader.read_notes_modified_since(timestamp)` for changed notes.
3. Call `bear_reader.read_trashed_pks()` for deletions.
4. For each changed note: delete old chunks from store, re-chunk, upsert.
5. For trashed notes: delete from store.
6. Write new timestamp to state file **only on success**.

**Design decision:** `index` (full rebuild) is implemented as `store.reset()` + full sync with timestamp `0`. One codepath for writing, not two.

### cli.py — Entry Point

Uses `argparse` with subcommands:

| Subcommand       | Description                                |
|------------------|--------------------------------------------|
| `bear-rag index` | Full rebuild (reset + sync from zero)      |
| `bear-rag sync`  | Incremental update since last sync         |
| `bear-rag sync --dry-run` | Print what would change, don't modify |
| `bear-rag ask "question"` | One-shot query + answer             |
| `bear-rag ask`   | Interactive REPL mode                      |
| `bear-rag status`| Last sync time, chunk count, note count    |

Loads `.env` file via `python-dotenv` at startup before any other initialization.

Entry point registered in `pyproject.toml` as `bear-rag = "bear_rag.cli:main"`.

## Persistent State

All persistent state lives under `~/.bear-rag/`:

| Path                          | Purpose                    |
|-------------------------------|----------------------------|
| `~/.bear-rag/chroma/`        | ChromaDB persistent storage|
| `~/.bear-rag/last_sync.json` | Sync timestamp state       |
| `~/.bear-rag/sync.log`       | Cron sync log output       |

This path is defined once as a config constant.

## Cron Setup

```
*/15 * * * * cd /path/to/bear-rag && uv run bear-rag sync >> ~/.bear-rag/sync.log 2>&1
```

## Testing Strategy

- **Framework:** pytest
- **`test_chunker.py`:** Edge cases — no headings, single heading, deeply nested, code blocks containing `#`, chunks that need secondary splitting, chunks that need merge-up.
- **`test_bear_reader.py`:** Uses a test SQLite fixture (copy of schema with synthetic data) to avoid depending on the real Bear DB.
- **`test_retriever.py`:** Integration test with a small in-memory ChromaDB collection and known documents, verifying that queries return expected results.

## Future Considerations (Out of Scope)

- Hybrid search (vector + tag filtering)
- Cross-encoder reranking
- Multi-turn conversation in REPL
- Web UI
- Docker packaging
- Additional note sources (Obsidian, plain Markdown)
