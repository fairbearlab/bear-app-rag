---
title: Evaluation Methodology
---

# Evaluation methodology

The eval asks a narrow question: does local semantic retrieval find the expected Bear notes more reliably than a reasonable keyword baseline on this corpus? It does not evaluate answer generation, production traffic, or every kind of personal note.

## Design

Both retrievers receive the same synthetic notes and queries:

1. **Semantic:** ChromaDB with all-MiniLM-L6-v2 ONNX embeddings. Each query is embedded and ranked by vector similarity.
2. **Keyword:** in-memory SQLite with `LIKE` matching. The query is tokenized, stop words are removed, matching words are counted across title and body, and notes are ranked by hit count.

The keyword path is intentionally more useful than a single substring search. It still cannot match a concept when the query and note share no vocabulary, which is the behavior the paraphrase and synonym groups are meant to expose.

Tag-filter cases take a different route. They call `mcp_server.search_notes()` against a Bear-schema fixture database so the eval exercises live tag resolution, the empty-filter guard, and ChromaDB together. Calling `NoteStore.query()` directly would skip the code under test.

## Corpus

The corpus contains 25 synthetic Bear notes across five domains:

| Domain | Notes | Purpose |
|--------|-------|---------|
| Recipes and cooking | 5 | Related terms such as flavor, taste, ingredients, and components |
| Travel and adventure | 5 | Budget, cost, journey, and trip vocabulary |
| Book notes | 5 | Concept summaries that invite paraphrased queries |
| Software engineering | 5 | Deploy, ship, release, and interface vocabulary |
| Personal journal | 5 | Queries that cross more than one topic |

The notes contain nested Markdown headings and vary from one to four chunks. They are committed at `tests/eval/fixtures/notes.json`.

## Queries

The current fixture contains 23 queries:

| Type | Count | Purpose |
|------|-------|---------|
| `exact_match` | 5 | Control group with query terms present verbatim in the notes |
| `synonym` | 5 | Different vocabulary for the same subject |
| `paraphrase` | 5 | Reworded concepts rather than shared keywords |
| `multi_concept` | 5 | Expected results spanning several notes or domains |
| `tag_single` | 1 | End-to-end precision for one tag |
| `tag_multi_or` | 1 | OR semantics and precision for two tags |
| `tag_no_match` | 1 | Empty result behavior for a tag with no notes |

Each query includes `expected_note_pks`, `expected_keywords`, and `answer_context`. Tag cases also include `tags`.

The three tag queries are correctness checks, not meaningful additions to the embedding model sample size. Model-quality conclusions still rest on the original 20 queries.

## Metrics

### Recall@K

Recall is the fraction of expected notes present in the top K unique note results. The benchmark uses K=5.

```text
recall@5 = |retrieved_top5 ∩ expected| / |expected|
```

### Mean reciprocal rank

MRR measures how early the first expected note appears.

```text
MRR = 1 / rank_of_first_expected_hit
```

### Keyword groundedness

Groundedness is the fraction of expected keywords found in the retrieved text.

```text
groundedness = |keywords_found_in_text| / |expected_keywords|
```

Semantic groundedness uses retrieved chunk text. Keyword groundedness uses the full text of the returned notes.

The metric functions return 1.0 when the expected set is empty. That convention makes the no-match tag case look perfect even if a broken filter returned unrelated notes, so the eval also asserts `len(results) == 0` and checks that tagged primary keys stay inside the expected tag universe. Metrics do not excuse missing negative assertions.

### Optional LLM judge

The judge asks Claude for a score from 0.0 to 1.0 describing whether the retrieved text supports answering the query. It scores semantic chunks and keyword note text with the same prompt and model (`config.CLAUDE_MODEL`). A full 23-query run makes 46 API calls.

The judge is useful but not deterministic. It requires `ANTHROPIC_API_KEY`, runs only when `EVAL_LLM_JUDGE=1` is set, and fails the run on API errors or malformed scores instead of writing a fake zero.

Judge scores are preserved across a judge-disabled run only when every query's retrieved primary keys and judged-text fingerprint still match the committed artifact. Any drift drops the entire judge column and asks for a fresh judged run. The current committed `results.json` contains deterministic metrics only, so the public benchmark does not report historical judge values as if they described the current 23-query artifact.

## Current results

From `tests/eval/results.json`:

| Metric | Semantic | Keyword (`LIKE`) |
|--------|----------|------------------|
| Recall@5 | 0.90 | 0.75 |
| MRR | 0.91 | 0.79 |
| Groundedness | 0.87 | 0.80 |

The original four query groups carry the useful interpretation:

| Query type | Recall semantic | Recall `LIKE` | MRR semantic | MRR `LIKE` |
|------------|-----------------|---------------|--------------|------------|
| `exact_match` | 1.00 | 1.00 | 1.00 | 1.00 |
| `multi_concept` | 0.83 | 0.73 | 0.84 | 0.90 |
| `paraphrase` | 1.00 | 0.60 | 0.77 | 0.44 |
| `synonym` | 0.83 | 0.70 | 1.00 | 0.70 |

Semantic retrieval clearly helps on paraphrases and synonyms. Exact matches tie. The multi-concept group has higher semantic recall and lower semantic MRR, so the benchmark does not support a blanket claim that vector search always ranks better.

## Running the eval

Deterministic run:

```shell
uv run pytest -m eval -v
```

With the optional judge:

```shell
EVAL_LLM_JUDGE=1 uv run pytest -m eval -v
```

The eval writes `tests/eval/results.json` and `tests/eval/BENCHMARK.md`. Review those changes before committing them; running a benchmark is also an artifact update.

## Artifacts

| File | Purpose |
|------|---------|
| `tests/eval/fixtures/notes.json` | Synthetic note corpus |
| `tests/eval/fixtures/queries.json` | Queries, ground truth, keywords, context, and tags |
| `tests/eval/results.json` | Current machine-readable result artifact |
| `tests/eval/BENCHMARK.md` | Generated result tables and examples |
| `tests/eval/eval_harness.py` | Corpus construction, retrievers, metrics, judge, and renderer |
| `tests/eval/test_eval.py` | Metric tests, directional assertions, tag gates, and artifact writes |
| `tests/eval/embedding_sweep.py` | Research harness for alternate local ONNX models |
| `tests/eval/embedding_comparison.json` | Committed alternate-model results |
| `tests/eval/embedding_comparison.md` | Rendered alternate-model comparison |

## Reproducibility

The committed result was generated on macOS ARM. ONNX Runtime can produce small numerical differences across platform backends, so tests assert the directional claims rather than exact floating-point values. The normal CI command excludes tests marked `eval`; run the eval explicitly when retrieval behavior, fixtures, chunking, or embedding configuration changes.

## Next useful work

- Expand the 20 retrieval-quality queries before drawing stronger model conclusions. Fifty notes and at least 40 quality queries would reduce the influence of any single fixture.
- Record platform, Python, ChromaDB, and ONNX Runtime versions in `results.json` so artifact drift is easier to diagnose.
- Re-test BGE and GTE with the asymmetric query and passage prefixes they expect, and repair the `gte-base` adapter path described in [ADR-0008](decisions/0008-embedding-model-evaluation.md).
