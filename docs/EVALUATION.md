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

### LLM Judge Groundedness

Claude scores (0.0-1.0) whether the retrieved text contains enough information to answer the query. Unlike keyword groundedness, the judge reads the text and reasons about whether it supports the answer, so it credits relevant retrievals that share no surface keywords. It runs on **both** retrieval paths — RAG chunk text and the LIKE note text — using the same model as the rest of the project (`config.CLAUDE_MODEL`, an undated alias). Requires `ANTHROPIC_API_KEY` and `EVAL_LLM_JUDGE=1`.

Committed results (from one `EVAL_LLM_JUDGE=1` run):

| Query Type | LLM-Judge RAG | LLM-Judge LIKE |
|------------|---------------|----------------|
| exact_match | 0.88 | 0.93 |
| synonym | 0.68 | 0.49 |
| paraphrase | 0.72 | 0.55 |
| multi_concept | 0.54 | 0.63 |
| **Overall** | **0.71** | **0.65** |

The judge corroborates the deterministic metrics: RAG wins on synonym and paraphrase queries (where the query wording diverges from the notes) and trails on exact_match and multi_concept (where the keyword baseline retrieves verbatim matches and ranks them well). On paraphrase queries q7 and q10, keyword search retrieved nothing relevant (recall 0.0) and the judge scored its retrieved text 0.0 — the sharpest illustration of the RAG advantage.

**Why it lives alongside, not inside, the deterministic source of truth.** The judge needs an API key, makes 40 calls per run, and is not bit-reproducible (the model's score varies run to run). So it runs only under `EVAL_LLM_JUDGE=1`; a plain `pytest -m eval` recomputes the deterministic metrics and carries the committed `llm_judge_*` columns forward unchanged rather than wiping them. The deterministic keyword groundedness remains the source of truth for CI's directional assertions, which never call the API.

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

## Roadmap / Future Work

Two improvements would strengthen the eval without changing the methodology:

- **Expand the eval corpus.** Scale from 25 notes / 20 queries to 50+ notes and 40+ queries for stronger statistical signal. The current corpus is sufficient for directional proof but honest about its limits (see [BUILDING.md](BUILDING.md) — "25 notes is honest but small").
- **Record a machine fingerprint in `results.json`.** Capture platform, Python version, and onnxruntime version alongside the numbers, so cross-platform embedding determinism can be tracked over time rather than inferred.
