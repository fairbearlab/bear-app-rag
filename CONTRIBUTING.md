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
- `ruff` (lint + format) and `mypy` are configured in `pyproject.toml` and enforced in CI.
  Run them locally with `make lint typecheck`, or install the pre-commit hooks once so they
  run on every commit:

  ```shell
  make hooks
  ```

## Secrets

The only credential this project ever needs is `ANTHROPIC_API_KEY`, and only for the
opt-in LLM-judge eval. Do not keep it in a plaintext `.env`. `.env.example` is a committed
[1Password CLI](https://developer.1password.com/docs/cli/secrets-environment-variables/)
reference file; `op run` injects the value into the child process only:

```shell
op run --env-file=.env.example -- env EVAL_LLM_JUDGE=1 uv run pytest -m eval -v
# or
make eval-judge
```

Point the `op://` reference at your own vault/item if it differs.

## What to Work On

- Issues labeled "good first issue"
- [Next useful eval work](docs/EVALUATION.md#next-useful-work) for deferred improvements
- The eval corpus needs more retrieval-quality notes and queries before stronger model
  claims are justified.

## Releases

Each release bumps `VERSION` and `pyproject.toml`, moves the `[Unreleased]` CHANGELOG entry
under a dated heading, and is tagged `vX.Y.Z` on the release commit.

## Running Tests

```shell
uv run pytest -v              # Default suite; eval-marked tests are excluded
uv run pytest -m eval -v      # Eval-marked tests only
uv run pytest -v -m ""        # Entire suite
make check                    # lint + typecheck + test + eval, as CI runs them
```
