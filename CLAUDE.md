# Working in this repo

Guidance for coding agents. Humans: see [CONTRIBUTING.md](CONTRIBUTING.md).

- **Verify before you finish.** `make check` runs ruff, mypy, the default pytest suite,
  and the eval suite — the same gates CI enforces. Keep all four green.
- **Never write to Bear's database.** `bear_reader.py` opens it read-only; keep it that way.
- **Keep the local-only boundary.** Indexing, sync, and search must not make network
  requests after the one-time model download (`tests/test_privacy.py` enforces this).
  Do not add a production dependency without an ADR-level reason; there are two.
- **Check the ADRs first.** [docs/decisions/](docs/decisions/) records the settled
  boundaries. Amend an ADR rather than quietly working around one.
- **Secrets never touch the tree.** The only credential is `ANTHROPIC_API_KEY` for the
  opt-in eval judge; inject it via `op run` (see `.env.example`), never a plaintext `.env`.
