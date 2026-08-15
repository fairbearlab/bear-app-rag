---
title: "Building a RAG Pipeline Without LangChain"
nav_title: Building It
---

# Building a RAG Pipeline Without LangChain

The engineering story behind bear-app-rag: a local semantic-search system for Bear notes built with two production dependencies, no orchestration framework, and a benchmark small enough to understand without pretending it settles retrieval science.

## Why I Built This

I keep most of my thinking in Bear. After a few hundred notes, finding the one I half-remembered became the bottleneck. Bear's search is keyword-based, and I rarely remember the exact wording I used.

I wanted plain-language retrieval without sending the index to a hosted embedding service. Answer generation is a separate choice: the MCP server returns selected excerpts to a connected agent, and that agent may be remote. Keeping those two boundaries separate made the project easier to reason about and the privacy claim easier to defend.

## The Problem

[Bear](https://bear.app) is a writing app for macOS and iOS. It stores notes in a local SQLite database. There is no API. There is no plugin system. Your notes are stored in that database.

One tempting approach is to pass whole notes to an agent and let its context window do the search. That works for a small selection. It stops being useful when the vault grows because the caller must either truncate the notes or spend context on material unrelated to the query.

What you actually want is semantic search. "What did I write about focus and productivity?" should find your Deep Work reading notes even if those exact words never appear in the text. The notes might use "concentration," "flow state," or "distraction-free environment." Keyword matching fails here. Embeddings don't.

## Why not LangChain?

Every RAG tutorial starts with `pip install langchain`. Here's what you get:

```
bear-app-rag (2 direct dependencies):
  chromadb
  mcp

Typical LangChain RAG setup (several direct and transitive packages):
  langchain
  langchain-community
  langchain-openai
  chromadb
  ... (framework and provider dependencies)
```

LangChain provides useful loaders, splitters, vector-store adapters, and orchestration for pipelines that need them. This project needs one reader, one chunker, and one vector store. Adding a wrapper around ChromaDB would give me another compatibility boundary without removing meaningful code.

The core indexing pipeline is three operations:

1. Read SQLite
2. Chunk text
3. Embed and query vectors

That is a reasonable amount of application code to own. Carrying a framework today would solve a future pipeline problem by creating a present dependency problem. The installed package uses `chromadb` and `mcp`; `anthropic` exists only in the development extra for the optional eval judge.

See [ADR-0001](decisions/0001-no-langchain.md) for the full reasoning.

## The Pipeline, Step by Step

### Step 1: Reading Bear's Database

Bear uses Core Data under the hood. The database lives at a predictable path in `~/Library/Group Containers/`. The notes table is `ZSFNOTE`. Tags live in a separate join table.

The gotcha nobody documents: Core Data stores timestamps as seconds since **2001-01-01 UTC**, not the Unix epoch (1970-01-01). If you parse `ZMODIFICATIONDATE` as a Unix timestamp, every note was "last modified" in 1970.

```python
CORE_DATA_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def _core_data_to_datetime(ts: float) -> datetime:
    return datetime.fromtimestamp(CORE_DATA_EPOCH.timestamp() + ts, tz=timezone.utc)
```

We open the database in read-only mode (`?mode=ro` in the SQLite URI). This is non-negotiable. Bear's database is the user's data. We never write to it, even by accident.

See `bear_reader.py:BearReader` for the implementation.

### Step 2: Chunking along document structure

Most RAG tutorials split text every N characters. This produces chunks that start mid-sentence and end mid-paragraph. The embedding for a chunk beginning with "...and the third reason is" has lost all context about what's being discussed.

Bear notes are Markdown. They have headings. Those headings are semantic boundaries the author placed deliberately. We split there.

```python
# chunker.py splits on ATX headings (#, ##, etc.)
# while respecting fenced code blocks
_HEADING_RE = re.compile(r"^(#{1,6}) (.+)$")
_FENCE_RE = re.compile(r"^```")
```

Three constants control the chunking:

- **300 words max** (~390 tokens). Fits within the embedding model's effective attention window.
- **30 words min.** Sections shorter than this merge upward. Prevents a heading like "## Notes" from becoming its own empty chunk.
- **40 words overlap.** When splitting oversized sections, the tail of each sub-chunk prepends to the next one.

Each chunk carries `heading_path` metadata (e.g., `"# Thai Green Curry > ## Ingredients"`). When an AI agent retrieves a chunk, it knows exactly where in the document it came from.

See `chunker.py:chunk_note` for the implementation and [ADR-0003](decisions/0003-chunk-sizing-strategy.md) for the sizing rationale.

### Step 3: Embeddings Without Leaving Your Machine

ChromaDB ships with ONNX Runtime and the all-MiniLM-L6-v2 model. No PyTorch, no sentence-transformers, no API keys. The model is ~90MB, downloaded once on first use, and runs on CPU.

```python
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction


class NoteStore:
    def __init__(self, persist_dir):
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._collection = self._client.get_or_create_collection(
            name="bear_notes",
            embedding_function=DefaultEmbeddingFunction(),
        )
```

After the initial model download, indexing, embedding, sync, and search do not initiate network requests. ChromaDB telemetry is disabled both through client settings and an import-time environment default. `tests/test_privacy.py` blocks outbound sockets and runs the storage and sync paths as a regression check.

The guarantee is deliberately narrow. The MCP server gives retrieved excerpts to the connected agent, and the optional eval judge calls Anthropic when enabled. Both are explicit trust boundaries. Neither changes how the local index is built or queried.

The model produces 384-dimensional vectors. ADR-0008 compares it with newer local models and keeps it for a less dramatic reason than "best model": the small eval did not show a large enough gain to justify a bigger model and a full re-index.

See `store.py:NoteStore` and [ADR-0002](decisions/0002-local-onnx-embeddings.md).

### Step 4: Making It Useful (MCP Server)

The CLI exists for admin tasks. The real interface is the MCP server: 6 tools that AI agents call during conversation.

| Tool | Purpose |
|------|---------|
| `search_notes` | Semantic search across all indexed notes |
| `read_note` | Read a specific note by title |
| `list_notes` | Browse notes with tag/date/title filters |
| `list_tags` | Show all tags with note counts |
| `sync_notes` | Trigger incremental sync from Bear |
| `status` | Show index stats and last sync time |

`search_notes` is the one worth showing in full, because its description doubles as UX copy for the agent:

```python
mcp = FastMCP("bear-notes")


@server.tool()
def search_notes(
    query: str,
    tags: list[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search notes by semantic similarity. Returns the most relevant chunks
    with title, text, tags, and heading path for citation."""
```

Tool descriptions are UX copy for machines. "Returns the most relevant chunks with title, text, tags, and heading path for citation" tells the agent exactly what it'll get back and how to use it.

The server runs over stdio. There is no listening port or shared service to configure. Add it to an MCP host and that host can call the tools during a conversation.

See `mcp_server.py` and [ADR-0004](decisions/0004-mcp-as-primary-interface.md).

### Step 5: Proving It Works (The Eval Framework)

"It feels better" is not a useful retrieval result. The eval compares semantic search with a SQLite `LIKE` baseline on a 25-note synthetic corpus.

The baseline is fair. We gave keyword search its best shot: split the query into words, LIKE-match each word against title and body, rank results by hit count. This is what a keyword-based Bear MCP server would do.

The current artifact contains 23 queries: 20 retrieval-quality cases across four query types and three end-to-end tag-filter cases. It reports three deterministic metrics. Higher is better: **Recall@5** is the fraction of expected notes in the top five results, **MRR** captures the rank of the first correct note, and **Groundedness** measures expected keyword coverage in the retrieved text. [EVALUATION.md](EVALUATION.md) defines each one.

| Metric | RAG | Keyword (LIKE) |
|--------|-----|----------------|
| Recall@5 | 0.90 | 0.75 |
| MRR | 0.91 | 0.79 |
| Groundedness | 0.87 | 0.80 |

The aggregate is useful orientation. The original four query types explain it:

| Query Type | Count | Recall RAG | Recall LIKE | MRR RAG | MRR LIKE |
|------------|-------|------------|-------------|---------|----------|
| exact_match | 5 | 1.00 | 1.00 | 1.00 | 1.00 |
| multi_concept | 5 | 0.83 | 0.73 | 0.84 | 0.90 |
| paraphrase | 5 | 1.00 | 0.60 | 0.77 | 0.44 |
| synonym | 5 | 0.83 | 0.70 | 1.00 | 0.70 |

On exact-match queries (the control group), both methods tie at 1.00. This confirms the baseline is fair.

On paraphrase queries, RAG beats keyword matching by 40%. When you search for "What makes products easy to use without reading instructions?" and the relevant note discusses "affordances" and "signifiers," keyword search has no chance. Embeddings understand that these concepts are related.

RAG does not win everywhere, and the table shows it. On multi_concept, RAG retrieves more of the expected notes (recall 0.83 vs 0.73) but the keyword baseline ranks its first hit higher (MRR 0.90 vs 0.84). The gap traces to one query — "weekend projects combining outdoor activity with food" — where RAG's first relevant hit lands at rank 5 and LIKE's at rank 2; the other four multi_concept queries tie at MRR 1.00. The win is on recall, not on first-hit rank.

The deterministic eval is pytest, JSON fixtures, and arithmetic. The optional LLM judge is useful for a different question, but it needs an API key and its results vary between runs, so it does not replace the deterministic checks.

See `tests/eval/eval_harness.py` and [ADR-0006](decisions/0006-hand-rolled-eval-framework.md).

## What I'd Do Differently

**Tag filtering mixes live and indexed state.** Tag membership comes from Bear's live SQLite database, while returned chunks come from the last index. A tag edit can therefore affect membership before the chunk metadata catches up. The next sync closes the gap. A single transactional snapshot would be cleaner, but it would require a different storage boundary.

**Twenty retrieval-quality queries are small.** The three tag cases check correctness rather than model quality, so the model comparison still rests on the original 20-query set. The results are directional evidence, not a general benchmark. Expanding the corpus is the next useful eval improvement.

**Chunk overlap is aggressive.** 40 words of overlap on 300-word chunks means ~13% duplication in the vector store. At small scale this is fine. At scale, you'd want configurable overlap or a smarter boundary-detection algorithm.

**There is no reranker.** A two-stage pipeline could improve precision after vector retrieval. It would also add another model, another latency budget, and another eval surface. That is a reasonable future problem. Carrying it today would be a present one.

**The reader depends on Bear's private schema.** It queries `ZSFNOTE`, `Z_5TAGS`, and `ZSFNOTETAG` directly. There is no compatibility layer if Bear changes those tables. The failure will be obvious, but it will still be a failure this project must repair.

**Status counts scan chunk metadata.** `get_stats()` derives the distinct note count by reading stored metadata. That is acceptable for an occasional status command and poor as a high-frequency metric. Tracking a second count would add state and reconciliation work, so the scan remains the simpler tradeoff for now.

## The Numbers

Run the eval yourself:

```shell
uv run pytest -m eval -v
```

With the optional LLM judge (requires `ANTHROPIC_API_KEY`, resolved from 1Password via the
committed `.env.example` reference file):

```shell
op run --env-file=.env.example -- env EVAL_LLM_JUDGE=1 uv run pytest -m eval -v
```

Or run the self-contained demo (no Bear database required):

```shell
uv run bear-rag demo
```

The committed `tests/eval/results.json` is the source for the public tables. Minor cross-platform differences are possible because ONNX Runtime uses different numerical backends. The tests assert the directional claims the project depends on rather than exact floating-point equality.
