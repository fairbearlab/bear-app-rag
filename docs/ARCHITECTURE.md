---
title: Architecture
---

# Architecture: How bear-app-rag Works

## The Pipeline (30-second version)

```text
Bear SQLite DB ──→ BearReader ──→ Chunker ──→ NoteStore (ChromaDB) ──→ MCP Server / CLI
   (read-only)     (Core Data      (markdown-     (ONNX embeddings,      (search, read,
                    timestamps)      aware split)   local vector store)    list, sync)
```

Two direct production dependencies: `chromadb`, `mcp`. Everything else is standard library. (`anthropic` is a dev-only extra used solely by the eval LLM judge — see below.)

## Reading Bear's Database

Bear stores notes in a Core Data SQLite database at `~/Library/Group Containers/9K33E3U3T4.net.shinyfrog.bear/Application Data/database.sqlite`. There is no Bear API. The database is the only interface.

`bear_reader.py:BearReader` opens the database in read-only mode (`?mode=ro` in the SQLite URI) so we never risk corrupting Bear's data. The class exposes methods for reading notes, listing tags, and querying by modification time.

**The 2001 epoch.** Core Data stores timestamps as seconds since 2001-01-01 UTC, not the Unix epoch (1970-01-01). This is an Apple-ism that nobody documents. `bear_reader.py:_core_data_to_datetime` handles the conversion. Every other part of the pipeline works in UTC datetimes.

**Tag fetching.** Bear stores tags in a separate join table (`Z_5TAGS`). `bear_reader.py:BearReader._fetch_tags_batch` batches tag lookups to avoid N+1 queries, chunking into groups of 900 to stay under SQLite's host-parameter limit.

See [ADR-0005](decisions/0005-incremental-sync-via-timestamps.md) for why we chose timestamp-based change detection.

## Chunking: Where Most RAG Pipelines Get It Wrong

Naive text splitting (every N characters) breaks mid-sentence, mid-paragraph, mid-thought. The embedding for a chunk that starts with "...and the third reason is" has no idea what the first two reasons were.

`chunker.py:chunk_note` splits on ATX headings (`#`, `##`, etc.) while respecting fenced code blocks. The heading hierarchy defines the document's semantic structure. When someone writes `## Ingredients` followed by `## Instructions`, those are distinct topics and should be separate chunks.

**The merge-up strategy.** Sections shorter than 30 words (the `MIN_CHUNK_WORDS` constant) get merged into the previous chunk. This prevents degenerate one-line headings like `## Notes` from becoming their own semantically empty chunk.

**Overlap.** When a section exceeds 300 words and must be split, the last 40 words of each sub-chunk overlap with the next. This preserves continuity across hard splits.

**Heading path metadata.** Each chunk carries a `heading_path` field (e.g., `"# Main Title > ## Sub-section"`). The MCP server surfaces this to AI agents, so they know where in the document structure a retrieved chunk came from.

See [ADR-0003](decisions/0003-chunk-sizing-strategy.md) for the sizing rationale.

## Embeddings: Local-First, No Cloud Required

`store.py:NoteStore` wraps ChromaDB with an explicitly pinned `DefaultEmbeddingFunction` (all-MiniLM-L6-v2 via ONNX Runtime). Every embedding is computed on-device. Indexing, embedding, and search never call a cloud service or a hosted vector DB.

The model produces 384-dimensional vectors. It's smaller than cloud alternatives (OpenAI's text-embedding-3-small produces 1536 dimensions), but at personal-note scale the quality difference doesn't matter, and the privacy guarantee does.

ChromaDB's telemetry is disabled at import time via `config.py:os.environ.setdefault('ANONYMIZED_TELEMETRY', 'False')`. ONNX Runtime makes no network calls during inference. On the indexing/embedding/search path the only network call is the one-time ~90MB model download on first use.

The installed package has zero cloud dependency, and this guarantee covers the whole shipped CLI: `index`, `sync`, and `status` never egress. There is one documented, opt-in boundary at runtime: the MCP server returns retrieved chunks to the connected agent, which then generates the answer — a deliberate trust boundary, not a gap in this codebase. Separately, dev-only tooling (the eval LLM judge in `tests/eval/eval_harness.py`) calls the Anthropic API to score retrieval quality; it ships behind the `dev` extra and never runs as part of the installed package.

See [ADR-0002](decisions/0002-local-onnx-embeddings.md) for the full privacy audit.

## Storage: ChromaDB Without the Framework

`store.py:NoteStore` is a thin wrapper around ChromaDB's `PersistentClient`. It handles:

- **Batched upserts** (`upsert_chunks`): chunks are written in groups of 100 to avoid memory spikes on large vaults.
- **$contains post-filtering** (`_extract_contains_filters`): ChromaDB's `$contains` operator doesn't work on metadata string fields. We extract these conditions and apply them in Python after the vector search. This lets the MCP server filter by tag substring (e.g., "find notes tagged with recipes").
- **Mixed $or handling**: When a `$or` clause mixes `$contains` and non-`$contains` conditions, we can't split without changing OR-to-AND semantics. The entire group gets evaluated in post-filtering.

The collection is persisted to `~/.bear-rag/chroma/` by default. A full re-index takes ~30s for 500 notes.

See [ADR-0001](decisions/0001-no-langchain.md) for why we use ChromaDB directly.

## The MCP Server: AI Agents as Primary Users

`mcp_server.py` exposes 6 tools via the Model Context Protocol:

| Tool | Purpose |
|------|---------|
| `search_notes` | Semantic search across all indexed notes |
| `read_note` | Read a specific note by title |
| `list_notes` | Browse notes with tag/date/title filters |
| `list_tags` | Show all tags with note counts |
| `sync_notes` | Trigger incremental sync from Bear |
| `status` | Show index stats and last sync time |

The server runs over stdio (no network transport). Tool descriptions are written as UX copy for AI agents: they explain what the tool does, when to use it, and what the return format looks like.

See [ADR-0004](decisions/0004-mcp-as-primary-interface.md) for the MCP-first design rationale.

## Sync: Incremental by Design

`sync.py:sync` only re-indexes notes that changed since the last run:

1. Read the last-sync timestamp from `~/.bear-rag/last_sync.json`
2. Query Bear for notes with `ZMODIFICATIONDATE > last_timestamp`
3. For each changed note: delete old chunks, chunk the new text, upsert
4. Query Bear for trashed note PKs, delete their chunks
5. Write the new timestamp

`sync.py:full_index` wipes the collection and re-syncs everything. Used for first-time setup and when the index schema version changes (tracked via `INDEX_VERSION` in config).

The `--dry-run` flag previews changes without modifying the store. The `--quiet` flag suppresses output when there's nothing to report, making it cron-friendly.

See [ADR-0005](decisions/0005-incremental-sync-via-timestamps.md) for the timestamp design.

## The Eval Framework: Proving It Works

`tests/eval/eval_harness.py` implements a dual-retriever benchmark comparing semantic search (ChromaDB) against keyword search (SQLite LIKE) on a 25-note synthetic corpus.

The eval doesn't use RAGAS, DeepEval, or any eval framework. It's pytest, JSON fixtures, and arithmetic. The metrics (recall@K, MRR, keyword groundedness) are hand-rolled with parametrized unit tests.

Results: semantic search beats keyword matching by +40% recall on paraphrase queries and +13% on synonym queries. On exact-match queries (the control group), both methods tie at 1.00.

See [ADR-0006](decisions/0006-hand-rolled-eval-framework.md) for the eval design, and [EVALUATION.md](EVALUATION.md) for methodology details.

## Module Summary

| Module | Lines | Purpose |
|--------|-------|---------|
| `bear_reader.py` | ~210 | Read notes and tags from Bear's SQLite database |
| `chunker.py` | ~150 | Markdown-aware splitting with heading hierarchy |
| `store.py` | ~210 | ChromaDB wrapper with $contains post-filtering |
| `sync.py` | ~150 | Incremental sync with Core Data timestamps |
| `mcp_server.py` | ~100 | MCP server with 6 tools for AI agents |
| `generator.py` | ~50 | Prompt construction and Claude API calls |
| `cli.py` | ~140 | argparse entry point with subcommands |
| `config.py` | ~30 | All constants and configuration |
| `models.py` | ~40 | Data classes (BearNote, Chunk, ChunkMetadata, SyncResult) |
