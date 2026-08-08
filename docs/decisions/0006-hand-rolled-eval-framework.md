---
title: "ADR-0006: Hand-Rolled Eval Framework"
---

# ADR-0006: Hand-Rolled Eval Framework

Status: Accepted
Date: 2026-04-07
Context: Phase 3 (eval framework)

## Context

bear-app-rag claims that semantic search improves retrieval when query wording differs from the note. That claim needs a repeatable comparison with a keyword baseline.

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

The original model-quality eval uses 20 queries across four types: `exact_match`, `synonym`, `paraphrase`, and `multi_concept`. Three later cases exercise single-tag, multi-tag OR, and no-match behavior through the MCP search path. Those cases test filter correctness; they do not enlarge the model-quality sample in a meaningful way.

## Alternatives Considered

**RAGAS:** Provides faithfulness, answer relevancy, and context precision metrics. Its LLM-backed metrics and generation-oriented model are more machinery than a deterministic retrieval comparison needs.

**DeepEval:** Similar to RAGAS with a nicer API. Same LLM-dependency and extra-dependency concerns. Also pushes toward their hosted dashboard.

**LangSmith:** Tracing and eval platform from LangChain. Requires account setup, cloud integration, and LangChain's evaluation abstractions. Contradicts our local-first, no-framework philosophy.

**BEIR benchmark format:** Good conceptual model (corpus, queries, qrels). We adopted its separation (notes.json, queries.json) without its three-file qrels format, since our ground truth embeds in queries.json as `expected_note_pks`.

## Consequences

### Positive
- The deterministic path uses the installed package plus pytest; no eval framework is needed
- Recall, MRR, and keyword groundedness run without an API key
- The metrics are defined in-repo, so anyone can read exactly how a score is computed
- Query type breakdown provides narrative depth that aggregate scores can't
- Public benchmark numbers trace back to the committed `results.json` artifact

### Negative
- No automatic faithfulness or hallucination detection (we test retrieval quality, not generation quality)
- The 25-note corpus and 20 model-quality queries are too small for broad model claims.
- Hand-rolled metrics could have bugs that framework-tested implementations wouldn't. Mitigated by parametrized unit tests for all metric functions.

### Neutral
- The LLM judge is opt-in via `EVAL_LLM_JUDGE=1` and remains separate from the deterministic source of truth
