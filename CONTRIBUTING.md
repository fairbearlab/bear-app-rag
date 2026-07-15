# Contributing to bear-app-rag

## Quick Start

```shell
git clone https://github.com/fairbearlab/bear-app-rag.git
cd bear-app-rag
uv sync --extra dev
uv run pytest -v
uv run pytest -m eval -v
```

## Try It First

Run the self-contained demo to understand how the pipeline works (no Bear database required):

```shell
uv run bear-rag demo
```

## Architecture

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the current module boundaries and
data flow.

## Design Decisions

Check [docs/decisions/](docs/decisions/) before changing an established boundary. If the
old decision no longer fits, add or amend an ADR and explain what changed.

## Code Style

- Use Python 3.11+ type hints.
- Add pytest coverage for behavior changes and regressions.
- Do not add a production dependency without recording why it belongs in the installed
  package.

## What to Work On

- Issues labeled "good first issue"
- [Next useful eval work](docs/EVALUATION.md#next-useful-work) for deferred improvements
- The eval corpus needs more retrieval-quality notes and queries before stronger model
  claims are justified.

## Running Tests

```shell
uv run pytest -v              # Default suite; eval-marked tests are excluded
uv run pytest -m eval -v      # Eval-marked tests only
uv run pytest -v -m ""        # Entire suite
```
