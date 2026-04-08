# bear-rag

Local RAG pipeline over [Bear](https://bear.app) notes. Indexes your notes into ChromaDB with local ONNX embeddings, then answers questions via Claude.

## Setup

```Shell
uv sync
cp .env.example .env   # then add your ANTHROPIC_API_KEY
```

Create a `.env` file with your Anthropic API key (only needed for the `ask` command):

```Shell
ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

```Shell
bear-rag index              # full rebuild — wipe and re-index all notes
bear-rag sync               # incremental update since last sync
bear-rag sync --dry-run     # preview what would change
bear-rag ask "question"     # one-shot query
bear-rag ask                # interactive REPL mode
bear-rag status             # show index stats and last sync time
```

### Auto-sync with cron

```Shell
*/15 * * * * cd /path/to/bear-rag && uv run bear-rag sync >> ~/.bear-rag/sync.log 2>&1
```

## Architecture

```text
Bear SQLite (read-only) → Chunker → ChromaDB (ONNX embeddings) → Claude API
```

| Module           | Purpose                                                  |
| ---------------- | -------------------------------------------------------- |
| `bear_reader.py` | Reads notes and tags from Bear's SQLite database         |
| `chunker.py`     | Markdown-aware splitting at headings with overlap        |
| `store.py`       | ChromaDB collection management (embed via built-in ONNX) |
| `generator.py`   | Prompt construction and Claude API calls                 |
| `sync.py`        | Incremental sync with timestamp-based change detection   |
| `cli.py`         | argparse entry point with subcommands                    |
| `mcp_server.py`  | MCP server exposing search, read, list, sync, status     |

Embeddings use ChromaDB's default `all-MiniLM-L6-v2` model via ONNX — no data leaves your machine unless you explicitly run `ask`.

## Configuration

All constants live in `bear_rag/config.py`:

| Constant            | Default                                          | Description                                  |
| ------------------- | ------------------------------------------------ | -------------------------------------------- |
| `BEAR_DB_PATH`      | `~/Library/Group Containers/.../database.sqlite` | Bear SQLite database path                    |
| `DATA_DIR`          | `~/.bear-rag`                                    | Persistent state directory                   |
| `CHROMA_DIR`        | `~/.bear-rag/chroma`                             | ChromaDB storage                             |
| `MAX_CHUNK_WORDS`   | 300                                              | Target max words per chunk (\~390 tokens)    |
| `MIN_CHUNK_WORDS`   | 30                                               | Below this, merge into adjacent chunk        |
| `OVERLAP_WORDS`     | 40                                               | Word overlap when splitting oversized chunks |
| `CLAUDE_MODEL`      | `claude-sonnet-4-20250514`                       | Model for answer generation                  |
| `CLAUDE_MAX_TOKENS` | 4096                                             | Max response tokens                          |

## Benchmarks

RAG vs keyword (SQLite LIKE) retrieval on a 25-note synthetic corpus with 20 eval queries across four query types. Results from `tests/eval/results.json`.

### Aggregate Metrics

| Metric       | RAG  | Keyword (LIKE) |
| ------------ | ---- | -------------- |
| Recall@5     | 0.92 | 0.65           |
| MRR          | 0.90 | 0.65           |
| Groundedness | 0.86 | 0.71           |

### By Query Type

| Query Type      | Count | Recall RAG | Recall LIKE | MRR RAG | MRR LIKE |
| --------------- | ----- | ---------- | ----------- | ------- | -------- |
| exact\_match    | 5     | 1.00       | 1.00        | 1.00    | 1.00     |
| multi\_concept  | 5     | 0.83       | 0.50        | 0.84    | 0.70     |
| paraphrase      | 5     | 1.00       | 0.40        | 0.77    | 0.30     |
| synonym         | 5     | 0.83       | 0.70        | 1.00    | 0.60     |

RAG wins decisively on paraphrase (+60%), multi-concept (+33%), and synonym (+13%) queries. On exact-match queries (the control group), both methods tie at 1.00 — confirming the baseline is fair.

### Side-by-Side Examples

**Query:** "How do our minds take shortcuts when making choices?"

- **RAG returns:** Thinking Fast and Slow, Deep Work, Atomic Habits, Design of Everyday Things
- **Keyword returns:** Sourdough Bread Baking, Meal Prep, Fermented Foods, Digital Nomad, Atomic Habits
- *Keyword matched "making" and "choices" literally; RAG understood the semantic meaning and found the cognitive biases note.*

**Query:** "How should I write software interfaces that other developers will enjoy using?"

- **RAG returns:** Pragmatic Programmer, Deploying Python Apps, API Design Best Practices, Learning Rust, Code Review Checklist
- **Keyword returns:** Atomic Habits, Thinking Fast and Slow, Design of Everyday Things, Deep Work, Pragmatic Programmer
- *RAG placed the API Design note in the top results; keyword search missed it entirely because "interfaces" appears in unrelated contexts.*

## Development

```Shell
uv sync --all-extras       # install dev dependencies
uv run pytest -v           # run tests
uv run pytest -m eval -v   # run eval suite only
```

To run the eval with the optional LLM judge (requires `ANTHROPIC_API_KEY`):

```Shell
EVAL_LLM_JUDGE=1 uv run pytest -m eval -v
```

