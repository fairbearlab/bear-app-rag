---
title: Evaluation Methodology
---

# Evaluation Methodology

How bear-app-rag proves that semantic search beats keyword matching for personal notes.

## Design

The eval compares two retrieval methods on the same corpus and queries:

1. **Semantic (RAG):** ChromaDB with all-MiniLM-L6-v2 ONNX embeddings. Query is embedded and matched by vector similarity.
2. **Keyword (LIKE):** In-memory SQLite with `LIKE '%word%'` matching. Query is split into words, each word is matched against note title and body, results ranked by hit count.

The keyword baseline is deliberately strong. We gave it every advantage: word splitting, stop word removal, multi-word hit counting, rank-by-relevance. This is what a keyword-based Bear MCP server would do.

## Corpus

25 synthetic Bear notes across 5 domains:

| Domain | Notes | Purpose |
|--------|-------|---------|
| Recipes/cooking | 5 | Synonym density ("flavor"/"taste", "ingredients"/"components") |
| Travel/adventure | 5 | Synonym density ("cost"/"expense"/"budget", "journey"/"trip") |
| Book notes/reading | 5 | Paraphrase-heavy (concept summaries) |
| Software engineering | 5 | Synonym density ("deploy"/"ship"/"release") |
| Personal journal | 5 | Multi-concept (crosses domains) |

Notes use realistic Bear markdown with nested headings so the chunker produces multiple chunks per note. Length varies from 1 to 4 chunks.

The corpus is committed at `tests/eval/fixtures/notes.json`.

## Queries

20 eval queries across 4 types:

| Type | Count | Purpose |
|------|-------|---------|
| `exact_match` | 5 | Control group. Query uses words that appear verbatim in notes. Keyword should do well. |
| `synonym` | 5 | Query uses different words than notes ("expenditure" when notes say "cost"). |
| `paraphrase` | 5 | Query rephrases concepts from notes. |
| `multi_concept` | 5 | Query combines topics across notes ("cooking techniques I learned while traveling"). |

Each query includes:
- `expected_note_pks`: ground truth notes that should be retrieved
- `expected_keywords`: terms that should appear in retrieved text (for groundedness scoring)
- `answer_context`: prose description of what a correct answer would cover (for LLM judge)

The queries are committed at `tests/eval/fixtures/queries.json`.

## Metrics

### Recall@K

Fraction of expected notes found in the top-K retrieved results. K=5 for all benchmarks.

```
recall@5 = |retrieved_top5 ∩ expected| / |expected|
```

### MRR (Mean Reciprocal Rank)

Reciprocal of the rank position where the first expected note appears.

```
MRR = 1 / rank_of_first_expected_hit
```

### Keyword Groundedness

Fraction of expected keywords found in the retrieved text. Deterministic, no API key required.

```
groundedness = |keywords_found_in_text| / |expected_keywords|
```

For RAG, "retrieved text" is the chunk text. For LIKE, it's the full note text of matched notes.

### LLM Judge Groundedness (Optional)

Claude scores (0.0-1.0) whether retrieved chunks contain enough information to answer the query. Requires `ANTHROPIC_API_KEY` and `EVAL_LLM_JUDGE=1` env var.

The LLM judge is available but **not part of the committed benchmark**. It needs an API key, so it is opt-in and its scores are not deterministic or checked into `results.json`. The deterministic keyword groundedness above is the source of truth for every number quoted in the README and the writeups; no LLM-judge figures are committed anywhere in this repo.

## Running the Eval

Default (no API key required):
```shell
uv run pytest -m eval -v
```

With LLM judge:
```shell
EVAL_LLM_JUDGE=1 uv run pytest -m eval -v
```

## Artifacts

| File | Purpose |
|------|---------|
| `tests/eval/results.json` | Committed artifact, source of truth for README numbers |
| `tests/eval/BENCHMARK.md` | Generated markdown report |
| `tests/eval/eval_harness.py` | All eval logic: corpus, retrievers, metrics, report renderer |
| `tests/eval/test_eval.py` | Pytest module with directional assertions and metric unit tests |

## Reproducibility

Results are generated on macOS ARM. ONNX Runtime uses different BLAS backends across platforms, which may cause minor floating-point differences. The directional results (RAG > LIKE on synonym/paraphrase) should hold everywhere. CI asserts directional wins only and does not regenerate `results.json`.
