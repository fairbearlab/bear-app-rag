# Changelog

All notable changes to bear-rag will be documented in this file.

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
