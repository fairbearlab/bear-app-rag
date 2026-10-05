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

## Known upstream advisories

ChromaDB 1.5.9 (the latest release, no fixed version available at the time of writing)
carries four open advisories, all scoped to the ChromaDB *HTTP server* and its auth layer:

- [PYSEC-2026-311 / CVE-2026-45829](https://github.com/chroma-core/chroma/issues/6717):
  pre-auth code injection via `trust_remote_code` on the collection-create endpoint.
- [PYSEC-2026-3813 / CVE-2026-45830](https://github.com/advisories/GHSA-2wm9-hf6c-p5cr):
  authenticated cross-tenant read/write/delete (server RBAC scoping bug).
- [PYSEC-2026-3814 / CVE-2026-45833](https://github.com/advisories/GHSA-36p7-vc44-83pf):
  authenticated code injection via `trust_remote_code` on the collection-update endpoint.
- [PYSEC-2026-3815 / CVE-2026-45831](https://github.com/advisories/GHSA-xph7-9rjv-w5fr):
  `SimpleRBACAuthorizationProvider` ignores tenant/db/collection scope.

This project uses `chromadb.PersistentClient` in-process (`bear_rag/store.py`), never
starts or exposes the HTTP server, and never configures chromadb's authn/authz providers,
so none of the vulnerable endpoints are reachable. The only remaining in-process path,
rebuilding an embedding function from persisted collection config, is written solely by
this process's own default ONNX embedding function; an attacker would already need write
access to the local Chroma directory. CI's `pip-audit` step (and `make audit`) ignores
these four IDs; each ignore is removed once a fixed release ships.

## What's already in place

- Dependencies are monitored by Dependabot; CI runs a vulnerability scan on every push.
- GitHub Actions are pinned to commit SHAs and run with minimal token permissions.
- This repository is scored by [OpenSSF Scorecard](https://scorecard.dev/viewer/?uri=github.com/fairbearlab/bear-app-rag).
