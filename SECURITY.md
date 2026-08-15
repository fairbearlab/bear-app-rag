# Security Policy

## Supported versions

Only the latest release of bear-app-rag receives security fixes.

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Use GitHub's private
vulnerability reporting: **Security → Report a vulnerability** on this repository.
You'll get an acknowledgement within 7 days.

## Local-first threat model

bear-app-rag runs entirely on your machine. Indexing, sync, and search make no network
requests after the one-time embedding-model download, and `tests/test_privacy.py`
enforces that boundary in CI. Your notes are read from Bear's SQLite database
**read-only** and are never uploaded anywhere. The only credential the project uses is
`ANTHROPIC_API_KEY` for the opt-in eval judge, which is injected at runtime and never
written to the tree.

This narrows the exposure: the realistic risks are local ones — a malicious note
influencing agent output through MCP, or the vector store leaking notes the user
expected to be excluded (archived and tag-filtered notes are covered by tests).

## Known upstream advisory

[PYSEC-2026-311 / CVE-2026-45829](https://github.com/chroma-core/chroma/issues/6717) is a
pre-authentication code-injection bug in the ChromaDB *HTTP server*, which has no fixed
release at the time of writing. This project uses `chromadb.PersistentClient` in-process
and never starts or exposes that server, so the vulnerable endpoint is not reachable. CI's
`pip-audit` step ignores this one ID; the ignore is removed once a fixed release ships.

## What's already in place

- Dependencies are monitored by Dependabot; CI runs a vulnerability scan on every push.
- GitHub Actions are pinned to commit SHAs and run with minimal token permissions.
- This repository is scored by [OpenSSF Scorecard](https://scorecard.dev/viewer/?uri=github.com/fairbearlab/bear-app-rag).
