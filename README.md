# bear-rag

Local RAG pipeline over [Bear](https://bear.app) notes. Indexes your notes into ChromaDB with local ONNX embeddings, then answers questions via Claude.

## Setup

```sh
uv sync
cp .env.example .env   # then add your ANTHROPIC_API_KEY
```

Create a `.env` file with your Anthropic API key (only needed for the `ask` command):

```sh
ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

```bash
bear-rag index              # full rebuild — wipe and re-index all notes
bear-rag sync               # incremental update since last sync
bear-rag sync --dry-run     # preview what would change
bear-rag ask "question"     # one-shot query
bear-rag ask                # interactive REPL mode
bear-rag status             # show index stats and last sync time
```

### Auto-sync with cron

```sh
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
| `retriever.py`   | Query interface over the vector store                    |
| `generator.py`   | Prompt construction and Claude API calls                 |
| `sync.py`        | Incremental sync with timestamp-based change detection   |
| `cli.py`         | argparse entry point with subcommands                    |

Embeddings use ChromaDB's default `all-MiniLM-L6-v2` model via ONNX — no data leaves your machine unless you explicitly run `ask`.

## Configuration

All constants live in `bear_rag/config.py`:

| Constant             | Default                                          | Description                                  |
| -------------------- | ------------------------------------------------ | -------------------------------------------- |
| `BEAR_DB_PATH`       | `~/Library/Group Containers/.../database.sqlite` | Bear SQLite database path                    |
| `DATA_DIR`           | `~/.bear-rag`                                    | Persistent state directory                   |
| `CHROMA_DIR`         | `~/.bear-rag/chroma`                             | ChromaDB storage                             |
| `MAX_CHUNK_WORDS`    | 300                                              | Target max words per chunk (~390 tokens)     |
| `MIN_CHUNK_WORDS`    | 30                                               | Below this, merge into adjacent chunk        |
| `OVERLAP_WORDS`      | 40                                               | Word overlap when splitting oversized chunks |
| `CLAUDE_MODEL`       | `claude-sonnet-4-20250514`                       | Model for answer generation                  |
| `CLAUDE_MAX_TOKENS`  | 4096                                             | Max response tokens                          |

## Development

```bash
uv sync --all-extras       # install dev dependencies
uv run pytest -v           # run tests
```
