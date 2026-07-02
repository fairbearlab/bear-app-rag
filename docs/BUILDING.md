---
title: "Building a Production RAG Pipeline Without LangChain"
---

# Building a Production RAG Pipeline Without LangChain

A technical essay on building bear-app-rag: a local-first semantic search system for Bear notes using 2 direct dependencies, zero frameworks, and provable benchmarks.

## Why I Built This

I keep most of my thinking in Bear. After a few hundred notes, finding the one I half-remembered became the bottleneck — Bear's search is keyword-only, and I rarely remember the exact words I used. I wanted to ask my notes a question in plain language and have the right ones surface, the same way I'd ask a colleague who'd read them. That meant semantic search, and I wanted the indexing and search to run on my own machine rather than shipping my notes off to a cloud service (asking an LLM to summarize a result is a separate, opt-in step). This project is the result, and I'm building it in the open as a portfolio piece — a small, fully-instrumented RAG pipeline I can point to and explain end to end.

## The Problem

[Bear](https://bear.app) is a writing app for macOS and iOS. It stores notes in a local SQLite database. There is no API. There is no plugin system. Your notes are locked in that database.

Existing Bear MCP servers take the brute-force approach: pass entire notes to the AI context window and let the model figure it out. That works until you have more than ~50 notes. At that point you're either truncating content or blowing past context limits.

What you actually want is semantic search. "What did I write about focus and productivity?" should find your Deep Work reading notes even if those exact words never appear in the text. The notes might use "concentration," "flow state," or "distraction-free environment." Keyword matching fails here. Embeddings don't.

## Why Not LangChain?

Every RAG tutorial starts with `pip install langchain`. Here's what you get:

```
bear-app-rag (2 direct dependencies):
  chromadb
  mcp

Typical LangChain RAG setup (4 direct + 50+ transitive):
  langchain
  langchain-community
  langchain-openai
  chromadb
  ... (50+ transitive dependencies pulled in)
```

LangChain wraps every library in an abstraction layer. You don't call ChromaDB. You call LangChain's ChromaDB wrapper, which calls ChromaDB. When something breaks, you debug through 6 layers of stack traces to find out that the underlying library just needed a different parameter.

The entire bear-app-rag pipeline is three operations:
1. Read SQLite
2. Chunk text
3. Embed into vectors, and let the MCP server query them for the connected agent

That's two libraries, not a framework. (`anthropic` is a dev-only extra for the eval LLM judge — never installed with the package.) The total production code is ~900 lines across 9 modules. Every line is debuggable. Every dependency is direct and justified.

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

### Step 2: Chunking That Actually Works

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

The privacy guarantee: the installed package never leaves the machine during indexing, embedding, sync, or search. The only network call on that path is that initial model download, and we disable ChromaDB's telemetry at import time. There is one documented, opt-in boundary: the MCP server hands retrieved chunks to the connected agent (Step 4 below), which then generates the answer — a deliberate trust boundary, not a gap. Separately, dev-only tooling (the eval LLM judge) calls the Anthropic API to score retrieval quality; it's behind the `dev` extra and never ships with the package.

The model produces 384-dimensional vectors. Cloud embedding APIs (OpenAI's text-embedding-3-small) produce 1536 dimensions. At personal-note scale, the quality difference doesn't matter. The privacy guarantee does.

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

@mcp.tool()
def search_notes(query: str, limit: int = 5, tag: str | None = None) -> list[dict]:
    """Search notes by semantic similarity. Returns the most relevant chunks
    with title, text, tags, and heading path for citation."""
```

Tool descriptions are UX copy for machines. "Returns the most relevant chunks with title, text, tags, and heading path for citation" tells the agent exactly what it'll get back and how to use it.

The server runs over stdio. No ports, no auth, no network config. Add it to `.mcp.json` and Claude Code can search your notes natively.

See `mcp_server.py` and [ADR-0004](decisions/0004-mcp-as-primary-interface.md).

### Step 5: Proving It Works (The Eval Framework)

"It feels like it works" isn't good enough for a portfolio project. We built a dual-retriever benchmark comparing semantic search against a SQLite LIKE baseline on a 25-note synthetic corpus.

The baseline is fair. We gave keyword search its best shot: split the query into words, LIKE-match each word against title and body, rank results by hit count. This is what a keyword-based Bear MCP server would do.

**The results.** Three metrics, all higher = better: **Recall@5** is the fraction of expected notes that appear in the top 5 results; **MRR** captures how high the first correct note ranks (1.0 = always first); **Groundedness** is the fraction of expected keywords present in the retrieved text. Full definitions are in [EVALUATION.md](EVALUATION.md).

| Metric | RAG | Keyword (LIKE) |
|--------|-----|----------------|
| Recall@5 | 0.92 | 0.76 |
| MRR | 0.90 | 0.76 |
| Groundedness | 0.86 | 0.80 |

The aggregate numbers are interesting. The per-query-type breakdown is where the story gets compelling:

| Query Type | Count | Recall RAG | Recall LIKE | MRR RAG | MRR LIKE |
|------------|-------|------------|-------------|---------|----------|
| exact_match | 5 | 1.00 | 1.00 | 1.00 | 1.00 |
| multi_concept | 5 | 0.83 | 0.73 | 0.84 | 0.90 |
| paraphrase | 5 | 1.00 | 0.60 | 0.77 | 0.44 |
| synonym | 5 | 0.83 | 0.70 | 1.00 | 0.70 |

On exact-match queries (the control group), both methods tie at 1.00. This confirms the baseline is fair.

On paraphrase queries, RAG beats keyword matching by 40%. When you search for "What makes products easy to use without reading instructions?" and the relevant note discusses "affordances" and "signifiers," keyword search has no chance. Embeddings understand that these concepts are related.

RAG does not win everywhere, and the table shows it. On multi_concept, RAG retrieves more of the expected notes (recall 0.83 vs 0.73) but the keyword baseline ranks its first hit higher (MRR 0.90 vs 0.84). The gap traces to one query — "weekend projects combining outdoor activity with food" — where RAG's first relevant hit lands at rank 5 and LIKE's at rank 2; the other four multi_concept queries tie at MRR 1.00. The win is on recall, not on first-hit rank.

The eval uses no frameworks. No RAGAS, no DeepEval, no LangSmith. Just pytest, JSON fixtures, and arithmetic.

See `tests/eval/eval_harness.py` and [ADR-0006](decisions/0006-hand-rolled-eval-framework.md).

## What I'd Do Differently

**The $contains post-filter is a hack.** ChromaDB doesn't support `$contains` on metadata strings. We extract those conditions and filter in Python after the vector search. This means we sometimes over-fetch candidates. At personal-note scale (~1000 notes) it doesn't matter. At 100K notes, you'd want a proper metadata index or a different vector database.

**25 notes is honest but small.** The eval corpus proves the concept, but the sample size limits statistical significance. The numbers tell a clear directional story, but they shouldn't be cited as rigorous benchmarks. Expanding to 50+ notes with 40+ queries is on the roadmap.

**Chunk overlap is aggressive.** 40 words of overlap on 300-word chunks means ~13% duplication in the vector store. At small scale this is fine. At scale, you'd want configurable overlap or a smarter boundary-detection algorithm.

**Single embedding model, no reranking.** A two-stage pipeline (cheap embeddings for recall, expensive reranker for precision) would improve MRR. Not worth the complexity for a personal-note corpus, but it's the obvious next step if quality needs to improve.

**The sync assumes Bear's schema is stable.** We query `ZSFNOTE`, `Z_5TAGS`, and `ZSFNOTETAG` directly. If Bear changes its Core Data schema in a major update, the reader breaks. There's no version negotiation. The mitigation is that Core Data schemas rarely change, and Bear's has been stable for years.

## The Numbers

Run the eval yourself:

```shell
uv run pytest -m eval -v
```

With the optional LLM judge (requires `ANTHROPIC_API_KEY`):

```shell
EVAL_LLM_JUDGE=1 uv run pytest -m eval -v
```

Or run the self-contained demo (no Bear database required):

```shell
uv run bear-rag demo
```

The committed `tests/eval/results.json` is the source of truth. The README benchmark tables are derived from it. If you re-run the eval and get different numbers, it's likely a platform difference in ONNX Runtime's BLAS backend (macOS ARM vs Linux x86). The directional results (RAG > LIKE on synonym/paraphrase) should hold everywhere.
