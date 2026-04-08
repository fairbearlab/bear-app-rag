# Changelog

All notable changes to bear-rag will be documented in this file.

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
