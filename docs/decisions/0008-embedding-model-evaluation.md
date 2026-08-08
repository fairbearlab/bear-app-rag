---
title: "ADR-0008: Embedding Model Evaluation"
---

# ADR-0008: Embedding Model Evaluation

Status: Accepted
Date: 2026-06-29
Context: Phase 5 (forward-looking evaluation). Amends [ADR-0002](0002-local-onnx-embeddings.md).

## Context

[ADR-0002](0002-local-onnx-embeddings.md) chose all-MiniLM-L6-v2 (384-dim, ONNX via ChromaDB's `DefaultEmbeddingFunction`) for local, no-network embeddings. That choice was made on reputation rather than a project-specific comparison. BGE, GTE, Snowflake Arctic, and Nomic provide small or base models with stronger scores than MiniLM on public benchmarks such as MTEB.

The question this ADR answers: **on _this_ corpus and these metrics, is any of them enough of an improvement to justify switching?** A switch is not free — a dimension change forces a full re-index, larger models cost disk and cold-start latency, and any new model must use a compatible MIT or Apache-2.0 license and no-network at inference to preserve the ADR-0002 guarantee.

## Method

The existing eval harness (`tests/eval/`) provides the scorer: 25 notes, 20 queries across four query types (exact_match, multi_concept, paraphrase, synonym), scored on Recall@5, MRR, and keyword Groundedness — the same metrics as the committed RAG-vs-keyword benchmark. `NoteStore` gained an optional `embedding_function` injection point so the harness can swap models; the shipped pipeline still defaults to MiniLM.

Candidate models were run via [`fastembed`](https://github.com/qdrant/fastembed) (Apache-2.0; ONNX Runtime, **no PyTorch**), declared as a research-only optional dependency (`pip install -e '.[research]'`), never a runtime dependency. The sweep harness is `tests/eval/embedding_sweep.py`; raw results are committed to `tests/eval/embedding_comparison.json` and rendered in `tests/eval/embedding_comparison.md`. Each candidate's weights download once from HuggingFace, then run fully offline — the same one-time-download / offline-after property MiniLM has.

**Candidate pool** (small/base English retrieval models, ONNX-via-fastembed, MIT or Apache-2.0): `bge-small-en-v1.5`, `bge-base-en-v1.5`, `gte-base`, `snowflake-arctic-embed-s`, `snowflake-arctic-embed-m`, `nomic-embed-text-v1.5`. **e5 and gte-small are intentionally absent**: fastembed does not package them as ONNX, so running them would require sentence-transformers + PyTorch (~2GB) — the dependency weight ADR-0002 rejected. The candidate set therefore reflects runtime feasibility as well as benchmark reputation.

## Results

| Model | Dim | License | Recall@5 | MRR | Groundedness | Disk | Re-index? |
|-------|-----|---------|----------|-----|--------------|------|-----------|
| **all-MiniLM-L6-v2** *(current)* | 384 | apache-2.0 | 0.92 | **0.90** | 0.86 | ~90MB | — |
| nomic-embed-text-v1.5 | 768 | apache-2.0 | **0.97** | 0.88 | **0.88** | 1096MB | yes |
| bge-small-en-v1.5 | 384 | mit | 0.93 | 0.87 | 0.86 | 134MB | no |
| bge-base-en-v1.5 | 768 | mit | 0.90 | 0.84 | 0.86 | 437MB | yes |
| snowflake-arctic-embed-m | 768 | apache-2.0 | 0.86 | 0.69 | 0.64 | 873MB | yes |
| snowflake-arctic-embed-s | 384 | apache-2.0 | 0.84 | 0.61 | 0.67 | 268MB | no |
| gte-base | 768 | mit | — | — | — | — | infeasible |

(Full per-query-type breakdown in `tests/eval/embedding_comparison.md`.)

The aggregate table favors nomic-embed-text-v1.5: +0.05 recall, +0.02 groundedness, and it wins the synonym and multi_concept subsets outright. The sample size does not establish that lead reliably.

## Decision

**Keep all-MiniLM-L6-v2.** No candidate clears the bar for a switch on the evidence available.

The reasoning is statistical, not aesthetic. With **n = 20 queries**, each query is 5% of any aggregate score and the binomial standard error on Recall@5 is ≈0.062 (95% CI half-width ≈±0.12). Nomic's apparent wins all sit **within one standard error of the mean**: a two-proportion test on the recall delta gives z ≈ 0.82, p ≈ 0.41 — indistinguishable from chance. The largest-looking signal, synonym recall +0.167, comes from an ≈6-query sub-corpus (SE ≈0.15) — one or two queries flipping. Against gains that are not statistically established, committing to nomic's concrete costs — **a 12× disk footprint (1096MB vs ~90MB) and a mandatory full re-index** (768-dim ⇒ bump `INDEX_VERSION`, no in-place migration) — is not justified. MiniLM also holds the **best MRR in the field (0.90)**: whatever it retrieves, it ranks first most reliably.

The drop-in alternative, bge-small-en-v1.5 (384-dim, no re-index, 134MB), is a genuine lateral move (+0.01 recall, −0.03 MRR) — and it was tested in the harness's **symmetric** embedding mode, with no asymmetric query/passage prefixes, which the BGE family is trained to expect. That likely _understates_ it, which is one reason it stays a live candidate for the follow-ups below rather than a reject.

This matches the project's stated posture (ADR-0003: "empirically chosen, not theoretically optimal"): there is no pressure to switch while MiniLM holds up, and on this corpus it does.

## What would change the decision

This is a "keep, for now, on this evidence" — not "MiniLM is optimal." Concrete follow-ups, in priority order, that could flip it:

1. **Expand the eval corpus to ≥100 queries** (already on the [EVALUATION roadmap](../EVALUATION.md)). At n=20 the experiment cannot distinguish a real 5-point gain from noise. nomic is the one model worth re-running first if the corpus grows, since its directional lean was the only consistent one.
2. **Re-test the BGE family with asymmetric prefixes.** ChromaDB calls one embedding function for both documents and queries, so the harness embeds them symmetrically. A fair BGE/GTE test needs `query:` / `passage:` prefixing; if prefixed bge-small closes its small gaps, a zero-cost 384-dim drop-in becomes the most attractive option and nomic's storage cost becomes moot.
3. **Fix the gte-base harness path.** gte-base failed with a numpy inhomogeneous-array error during upsert — a fastembed/adapter output-shape issue, **not** a model-quality verdict. It is currently untestable here and should not be dismissed on this run.

If a switch is ever made, bump `INDEX_VERSION` in `config.py` (stored vectors change) and document the one-time re-index in the README.

## Consequences

### Positive
- The ADR-0002 model choice is now measured against current alternatives, not asserted — and the harness to re-measure exists and is committed.
- `NoteStore` is model-swappable, so a future switch is a one-line change plus a re-index, not a refactor.
- The candidate-pool feasibility filter (no PyTorch, ONNX, compatible license) is documented, so the "why not e5/gte-small" question is answered.

### Negative
- The verdict rests on an underpowered n=20 corpus, so "keep" remains provisional pending a larger comparison.
- `fastembed` is an extra (research-only) dependency to maintain, even though it never ships at runtime.

### Neutral
- All evaluated models are MIT or Apache-2.0; none would have introduced a licensing conflict had it won.
