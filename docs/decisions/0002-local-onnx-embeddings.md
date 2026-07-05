---
title: "ADR-0002: Local ONNX Embeddings"
---

# ADR-0002: Local ONNX Embeddings

Status: Accepted
Date: 2026-03-25
Context: Phase 1 (initial design), amended Phase 4 (privacy audit)

## Context

Embedding generation is the core of semantic search. The choice of embedding approach determines privacy guarantees, latency, cost, and operational complexity.

Bear notes are personal. Users store journal entries, health notes, financial plans, and private thoughts. Sending this content to a cloud embedding API contradicts the local-first promise.

## Decision

Use ChromaDB's built-in `DefaultEmbeddingFunction` which runs all-MiniLM-L6-v2 via ONNX Runtime locally. Indexing, embedding, and search run entirely on-device; no note content is sent to a cloud service on that path.

**Privacy audit results (Phase 4):** ChromaDB includes opt-out telemetry (`ANONYMIZED_TELEMETRY` env var). We disable it at import time in `config.py:os.environ.setdefault`. ONNX Runtime makes no network calls during inference. On the indexing/embedding/search path the only network call is the one-time ~90MB model download on first use, fetched from ChromaDB's S3 bucket (`chroma-onnx-models.s3.amazonaws.com`).

**Enforcement:** this guarantee is regression-tested, not just documented. `tests/test_privacy.py` pre-warms the model cache, blocks all outbound network sockets (via `pytest-socket`), and asserts that `NoteStore` construction, `upsert_chunks`, `query`, and `sync` all still succeed — with a negative-control test proving the socket block is actually installed. The eval LLM judge (`tests/eval/eval_harness.py`) is deliberately excluded, since it legitimately calls the Anthropic API as dev-only tooling; it never ships with the installed package (D1, ADR history below).

**Scope of the guarantee.** The installed package has zero cloud dependency: `index`, `sync`, `search`, and `status` never egress. One path is opt-in at runtime and outside this codebase's control: the MCP server returns retrieved chunks to whatever agent is connected, which then generates the answer — a trust boundary the user opts into by wiring up the server, not a gap in the local-only claim. Separately, the eval LLM judge is a dev-only, opt-in caller of the Anthropic API used to score retrieval quality; it is never installed or run as part of the shipped package. The privacy claim is about embedding and retrieval, not about answer generation, which happens entirely outside this repo (the connected agent, or the dev-only eval judge).

**History:** an earlier `bear-rag ask` CLI command generated answers locally by calling the Anthropic API directly. It was removed (2026-07) as a redundant, worse re-implementation of what the MCP path already does — see [ADR-0004](0004-mcp-as-primary-interface.md) for why.

The embedding model (all-MiniLM-L6-v2) is pinned via explicit `DefaultEmbeddingFunction()` in `store.py` to ensure reproducibility across ChromaDB versions. `NoteStore` exposes an optional `embedding_function` injection point so alternate local models can be benchmarked, but the production default is unchanged.

**Model choice is now measured, not asserted (Phase 5).** [ADR-0008](0008-embedding-model-evaluation.md) ran the BGE, GTE, Snowflake Arctic, and Nomic families through the eval harness and concluded: keep all-MiniLM-L6-v2. No candidate's gains cleared statistical noise on the n=20 corpus, and the only model that led directionally (nomic-embed-text-v1.5) would have cost a 12× disk footprint and a full re-index. See ADR-0008 for the comparison table and the follow-ups that could change the call.

## Alternatives Considered

**OpenAI Embeddings API:** Higher quality embeddings (text-embedding-3-small), but every indexing and query operation sends note content to OpenAI's servers. Also adds per-token cost and network latency.

**Sentence Transformers (PyTorch):** More model choices and fine-tuning options, but pulls in PyTorch (~2GB) as a dependency. Overkill for inference-only use.

**Cohere Embed API:** Good quality, but same cloud privacy and cost concerns as OpenAI.

## Consequences

### Positive
- No note content leaves the machine during indexing, embedding, sync, or search (the MCP server's hand-off to the connected agent is the one documented, opt-in exception)
- Zero per-query cost after the one-time model download
- Works offline after first run
- ChromaDB handles the ONNX Runtime lifecycle, so we don't manage model loading

### Negative
- all-MiniLM-L6-v2 produces 384-dim vectors, lower quality than cloud models (1536-dim for OpenAI)
- First run requires ~90MB download and ~30s extra for model caching
- CPU-only inference is slower than GPU-accelerated cloud APIs (acceptable at personal note scale)

### Neutral
- all-MiniLM-L6-v2 is Apache 2.0 licensed, distinct from this repo's MIT license. No licensing conflict.
