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

**Enforcement:** `tests/test_privacy.py` pre-warms the model cache, blocks outbound network sockets with `pytest-socket`, and exercises `NoteStore` construction, `upsert_chunks`, `query`, and `sync`. A negative control confirms the socket block is installed. The eval judge is excluded because its explicit purpose is to call Anthropic as development tooling.

**Scope of the guarantee.** The installed package has no cloud SDK. `index`, `sync`, `search`, and `status` do not initiate network requests after the model download. The MCP server does return retrieved chunks to the connected agent, which may use a remote service. The development-only eval judge calls Anthropic when explicitly enabled. The claim covers
local embedding and retrieval; it does not claim that every consumer of retrieved text is offline.

**History:** an earlier `bear-rag ask` command called Anthropic from the installed application. It was removed in 2026-07 after MCP made that answer path redundant. See [ADR-0004](0004-mcp-as-primary-interface.md).

The embedding model (all-MiniLM-L6-v2) is pinned via explicit `DefaultEmbeddingFunction()` in `store.py` to ensure reproducibility across ChromaDB versions. `NoteStore` exposes an optional `embedding_function` injection point so alternate local models can be benchmarked, but the production default is unchanged.

**Model comparison (Phase 5).** [ADR-0008](0008-embedding-model-evaluation.md) ran BGE, GTE, Snowflake Arctic, and Nomic candidates through the eval harness. The 20-query sample did not establish a gain large enough to justify switching, and the directionally strongest candidate required roughly twelve times the disk space plus a full re-index.

## Alternatives Considered

**OpenAI Embeddings API:** Higher quality embeddings (text-embedding-3-small), but every indexing and query operation sends note content to OpenAI's servers. Also adds per-token cost and network latency.

**Sentence Transformers (PyTorch):** More model choices and fine-tuning options, but pulls in PyTorch (~2GB) as a dependency. Overkill for inference-only use.

**Cohere Embed API:** Good quality, but same cloud privacy and cost concerns as OpenAI.

## Consequences

### Positive
- No note content leaves the machine during indexing, embedding, sync, or search; the MCP handoff is a separate, opt-in boundary
- Zero per-query cost after the one-time model download
- Works offline after first run
- ChromaDB handles the ONNX Runtime lifecycle, so we don't manage model loading

### Negative
- all-MiniLM-L6-v2 produces 384-dim vectors, lower quality than cloud models (1536-dim for OpenAI)
- First run requires ~90MB download and ~30s extra for model caching
- CPU-only inference is slower than GPU-accelerated cloud APIs (acceptable at personal note scale)

### Neutral
- all-MiniLM-L6-v2 is Apache 2.0 licensed, distinct from this repo's MIT license. No licensing conflict.
