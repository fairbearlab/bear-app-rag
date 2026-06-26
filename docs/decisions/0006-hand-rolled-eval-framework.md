---
title: "ADR-0006: Hand-Rolled Eval Framework"
---

# ADR-0006: Hand-Rolled Eval Framework

Status: Accepted
Date: 2026-04-07
Context: Phase 3 (eval framework)

## Context

bear-app-rag claims that semantic search beats keyword matching for finding relevant notes. Claims need proof. The question: how do we prove it?

The RAG evaluation ecosystem has mature frameworks (RAGAS, DeepEval, LangSmith). Using one would be the conventional choice.

## Decision

Build a hand-rolled eval harness using pytest, JSON fixtures, and arithmetic. No eval framework dependencies.

The harness (`tests/eval/eval_harness.py`) implements:
- `EvalCorpus`: loads a 25-note synthetic corpus, indexes into both ChromaDB (semantic) and in-memory SQLite (keyword LIKE baseline)
- `recall_at_k`, `mrr`: standard IR metrics, computed per-query
- `keyword_groundedness`: fraction of expected keywords found in retrieved text (deterministic, no API key)
- `llm_judge_groundedness`: optional Claude-scored answer quality (requires API key, gated by env var)
- `run_eval`: iterates queries through both retrievers, computes all metrics
- `render_report`: generates markdown tables and side-by-side examples from results.json

The eval uses 20 queries across 4 types: exact_match (control group), synonym, paraphrase, and multi_concept. The type breakdown tells a story that a single aggregate score can't.

## Alternatives Considered

**RAGAS:** Popular RAG eval framework. Provides faithfulness, answer relevancy, and context precision metrics out of the box. But it requires an LLM for every metric computation (expensive, non-deterministic), adds 15+ transitive dependencies, and its metrics are optimized for RAG-with-generation, not retrieval-only comparison.

**DeepEval:** Similar to RAGAS with a nicer API. Same LLM-dependency and extra-dependency concerns. Also pushes toward their hosted dashboard.

**LangSmith:** Tracing and eval platform from LangChain. Requires account setup, cloud integration, and LangChain's evaluation abstractions. Contradicts our local-first, no-framework philosophy.

**BEIR benchmark format:** Good conceptual model (corpus, queries, qrels). We adopted its separation (notes.json, queries.json) without its three-file qrels format, since our ground truth embeds in queries.json as `expected_note_pks`.

## Consequences

### Positive
- Zero eval dependencies beyond pytest (already a dev dependency)
- Deterministic by default: keyword_groundedness runs without any API key
- The metrics are defined in-repo, so anyone can read exactly how a score is computed
- Query type breakdown provides narrative depth that aggregate scores can't
- Results committed as `results.json` artifact, README numbers always traceable

### Negative
- No automatic faithfulness or hallucination detection (we test retrieval quality, not generation quality)
- The 25-note synthetic corpus is small. Honest about this in the writeup, with a TODO to scale to 50+.
- Hand-rolled metrics could have bugs that framework-tested implementations wouldn't. Mitigated by parametrized unit tests for all metric functions.

### Neutral
- LLM judge is opt-in via `EVAL_LLM_JUDGE=1` env var, so the full eval is available when needed
