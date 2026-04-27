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

Use ChromaDB's built-in `DefaultEmbeddingFunction` which runs all-MiniLM-L6-v2 via ONNX Runtime locally. No embedding data leaves the machine.

**Privacy audit results (Phase 4):** ChromaDB includes opt-out telemetry (`ANONYMIZED_TELEMETRY` env var). We disable it at import time in `config.py:os.environ.setdefault`. ONNX Runtime makes no network calls during inference. The only network call is the one-time ~90MB model download on first use, fetched from ChromaDB's S3 bucket (`chroma-onnx-models.s3.amazonaws.com`).

The embedding model (all-MiniLM-L6-v2) is pinned via explicit `DefaultEmbeddingFunction()` in `store.py` to ensure reproducibility across ChromaDB versions.

## Alternatives Considered

**OpenAI Embeddings API:** Higher quality embeddings (text-embedding-3-small), but every indexing and query operation sends note content to OpenAI's servers. Also adds per-token cost and network latency.

**Sentence Transformers (PyTorch):** More model choices and fine-tuning options, but pulls in PyTorch (~2GB) as a dependency. Overkill for inference-only use.

**Cohere Embed API:** Good quality, but same cloud privacy and cost concerns as OpenAI.

## Consequences

### Positive
- Zero data exfiltration: no note content leaves the machine during indexing or querying
- Zero per-query cost after the one-time model download
- Works offline after first run
- ChromaDB handles the ONNX Runtime lifecycle, so we don't manage model loading

### Negative
- all-MiniLM-L6-v2 produces 384-dim vectors, lower quality than cloud models (1536-dim for OpenAI)
- First run requires ~90MB download and ~30s extra for model caching
- CPU-only inference is slower than GPU-accelerated cloud APIs (acceptable at personal note scale)

### Neutral
- all-MiniLM-L6-v2 is Apache 2.0 licensed, distinct from this repo's MIT license. No licensing conflict.
