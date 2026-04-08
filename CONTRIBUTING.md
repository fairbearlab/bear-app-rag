# Contributing to bear-app-rag

## Quick Start

```shell
git clone https://github.com/fairbearlab/bear-app-rag.git
cd bear-app-rag
uv sync
uv run pytest -v
uv run pytest -m eval -v
```

## Try It First

Run the self-contained demo to understand how the pipeline works (no Bear database required):

```shell
uv run bear-rag demo
```

## Architecture

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for a full tour of every module.

## Design Decisions

Check [docs/decisions/](docs/decisions/) for ADRs explaining why things are the way they are. If your change contradicts an existing ADR, write a new ADR documenting why.

## Code Style

- Python 3.11+ type hints
- pytest for testing
- No new production dependencies without an ADR

## What to Work On

- Issues labeled "good first issue"
- [TODOS.md](TODOS.md) for deferred work
- The eval corpus can always use more notes and queries

## Running Tests

```shell
uv run pytest -v              # Unit tests (131 tests)
uv run pytest -m eval -v      # Eval suite (27 tests)
uv run pytest -v -m ""        # All tests
```
