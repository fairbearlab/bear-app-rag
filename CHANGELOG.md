# Changelog

All notable changes to bear-rag will be documented in this file.

## [0.3.2] - 2026-06-28

### Added

- First-person "Why I Built This" section near the top of `docs/BUILDING.md`, scoped honestly (indexing and search run locally; the LLM `ask` step is opt-in).
- Mermaid "How It Works" flowchart in the README, replacing the ASCII diagram. It shows the read-only Bear source, the on-device pipeline, and the opt-in cloud paths (`ask` and the MCP-returns-chunks boundary), with module names aligned to the Project Structure table.
- "Roadmap / Future Work" section in `docs/EVALUATION.md` (expand the eval corpus to 50+ notes / 40+ queries; record a machine fingerprint in `results.json`).
- README callout that the same stdio server should work with any MCP-compatible host (Codex CLI, GitHub Copilot agent mode, Claude desktop app), noting that only the Claude Code config is tested.

### Changed

- Expanded `.gitignore` with a thorough Python template (`.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `.coverage`, `htmlcov/`, `*.log`, `.idea/`, `.vscode/`, `.claude/`), preventive — none were tracked.
- `.python-version` 3.14 → 3.13, the highest version in the tested CI matrix (`requires-python` floor and README "3.11+" unchanged).
- `scripts/showcase.sh` now `mkdir -p docs/assets` before recording, so the demo recording works without a pre-existing directory; `scripts/record-demo.sh` documents the required `mkdir -p docs/assets` in its usage line (the directory must exist before `asciinema` is invoked, which runs `record-demo.sh` as its command, so the script can't create it itself).

### Removed

- `TODOS.md` (internal phase-tracking bookkeeping). Its two forward-looking items moved into the new `docs/EVALUATION.md` roadmap; `CONTRIBUTING.md` now points there instead.

## [0.3.1] - 2026-06-27

### Added

- Privacy guardrail test (`tests/test_privacy.py`): blocks all outbound network sockets (via `pytest-socket`) and asserts `NoteStore` construction, `upsert_chunks`, `query`, and `sync` all run offline, enforcing the ADR-0002 local-only guarantee. Includes a negative-control test so it can't pass vacuously. The `ask` / generator path is excluded — it legitimately calls the Anthropic API.
- Committed LLM-judge groundedness column in the eval benchmark: Claude scores how well retrieved text supports each query, run on both the RAG and keyword paths. Surfaced in `results.json`, `BENCHMARK.md`, the README, the benchmark visualization, and `docs/EVALUATION.md` (RAG 0.71 vs keyword 0.65 overall; widest gap on paraphrase queries, 0.72 vs 0.55).
- `pytest-socket` dev dependency (in the `dev` optional-dependencies extra, so `pip install -e ".[dev]"` and `uv` both install it).

### Changed

- LLM judge now fails closed: an API error or a non-numeric model reply raises `LLMJudgeError` instead of silently committing a `0.0` score as benchmark truth.
- `_carry_forward_judge` preserves committed judge numbers across deterministic re-runs only when the judged text is unchanged (fingerprinted on a content hash of the exact text the judge scored, `semantic_text_sha` / `like_text_sha`, with a PK fallback for legacy results); it drops the column and warns on drift, so stale scores are never presented against new retrieval — including re-chunking or note edits that leave the retrieved PKs identical.
- Refreshed locked dependencies (`uv lock --upgrade`): `anthropic` 0.86→0.112, `chromadb` 1.5.5→1.5.9, `mcp` 1.26→1.28.1, `pytest` 9.0→9.1.1 — all within existing version caps. Directional eval results hold and `results.json` is byte-identical across the `onnxruntime`/`tokenizers` bump.

### Fixed

- LLM judge fail-closed now also rejects non-finite replies (`nan`/`inf`, which `float()` accepts and would clamp to a fake `1.0`) and an unexpected SDK response shape (empty/non-text content), both raising `LLMJudgeError` instead of slipping through as a real score.
- `pytest-socket` moved from a `[dependency-groups]` (uv-only, PEP 735) block into the `dev` optional-dependencies extra alongside `pytest`, so a `pip install -e ".[dev]"` no longer fails to import `pytest_socket` when collecting `tests/test_privacy.py`.
- `_metrics_for` no longer raises `KeyError` on heterogeneous judge data (gates the judge columns on every query carrying them, not just the first).
- `test_ask_requires_api_key` is now hermetic: it stubs `load_dotenv` so a developer's local `.env` can't re-supply the key the test deliberately removes.

## [0.3.0] - 2026-04-08

### Added

- `bear-rag demo` command: self-contained benchmark demo comparing RAG vs keyword search. No Bear database or API key required. Uses an inline 5-note corpus with retrieval timing.
- Architecture documentation (`docs/ARCHITECTURE.md`): narrative tour of every module with tradeoff analysis
- Long-form technical essay (`docs/BUILDING.md`): "Building a Production RAG Pipeline Without LangChain"
- Evaluation methodology documentation (`docs/EVALUATION.md`)
- 7 Architecture Decision Records (ADRs) in `docs/decisions/`: no-langchain, local-onnx-embeddings, chunk-sizing, mcp-as-primary-interface, incremental-sync, hand-rolled-eval, mit-license
- Benchmark visualization: static SVG charts generated from results.json (`docs/benchmarks/index.html`)
- GitHub Pages docs site with Jekyll minimal theme
- `scripts/showcase.sh`: one-command artifact regeneration (eval, viz, markdown, recording)
- `scripts/record-demo.sh`: reproducible terminal recording script
- `scripts/generate-benchmark-viz.py`: Python-generated SVG benchmark charts
- CONTRIBUTING.md with development quickstart
- LICENSE (MIT)
- `.github/FUNDING.yml` for GitHub Sponsors

### Changed

- README rewritten as landing page: quickstart, architecture diagram, benchmark tables, ADR links, CLI reference
- Pinned embedding function: `DefaultEmbeddingFunction()` explicitly passed in `store.py` for reproducibility
- `EMBEDDING_MODEL` constant added to `config.py` for documentation
- ChromaDB telemetry disabled at import time via `os.environ.setdefault` in `config.py`
- PyPI metadata added to `pyproject.toml`: description, authors, license, classifiers, repository URL

### Fixed

- Resolved all deferred TODOS.md items from Phase 1 (privacy audit) and Phase 4 (PyPI metadata, embedding pin, model download docs)

## [0.2.1] - 2026-06-26

### Fixed

- Bumped `CLAUDE_MODEL` off the retired `claude-sonnet-4-20250514` snapshot (retired 2026-06-15) to the undated `claude-sonnet-4-6` alias, so the `bear-rag ask` / LLM-judge path keeps working and won't 404 after a future snapshot retirement. Also fixed the same hardcoded snapshot in `tests/eval/eval_harness.py`.

## [0.2.0] - 2026-04-07

### Added

- Eval framework comparing RAG vs keyword (SQLite LIKE) retrieval with recall@K, MRR, and keyword groundedness metrics
- 25-note synthetic corpus across 5 domains (recipes, travel, books, engineering, journal) with deliberate synonym density and thematic overlap
- 20 eval queries in 4 types: exact match, synonym, paraphrase, and multi-concept
- Optional LLM judge for answer groundedness scoring (requires ANTHROPIC_API_KEY)
- Benchmark results table in README with aggregate metrics, per-query-type breakdown, and side-by-side examples
- MCP server configuration (.mcp.json) for Claude Code integration
- pytest `eval` marker for running eval suite separately (`uv run pytest -m eval -v`)

### Changed

- Fixed stale architecture table in README (removed retriever.py, added mcp_server.py)

### Fixed

- LIKE tokenizer now strips trailing punctuation and escapes SQL wildcards for fair baseline comparison
