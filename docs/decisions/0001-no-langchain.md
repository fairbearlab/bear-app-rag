---
title: "ADR-0001: No LangChain"
---

# ADR-0001: No LangChain

Status: Accepted
Date: 2026-03-25
Context: Phase 1 (initial design)

## Context

LangChain is a common starting point for projects involving embeddings, vector stores, and LLM orchestration. This project still needs to justify owning those connections directly.

We evaluated LangChain for the Bear notes pipeline and found a mismatch between what we need and what it provides.

## Decision

Build the RAG pipeline with direct library calls (chromadb, mcp) instead of LangChain or any orchestration framework.

The core pipeline has four operations: read SQLite, chunk text, embed vectors, and query them. Two direct libraries cover the non-standard-library work.

## Alternatives Considered

**LangChain:** Provides document loaders, splitters, vector-store wrappers, and chain abstractions. Those are useful in a larger or more variable pipeline. Here they would add a transitive dependency tree and a wrapper compatibility boundary around ChromaDB without removing much application code.

**LlamaIndex:** Similar scope to LangChain with a data-focused orientation. Same dependency and abstraction concerns.

**Haystack:** More opinionated pipeline framework. Good for complex multi-stage retrieval but overkill for a single-collection semantic search.

## Consequences

### Positive
- 2 direct dependencies total (chromadb, mcp) — even fewer than the pipeline originally shipped with, after `ask` was removed and `anthropic`/`python-dotenv` dropped from production (ADR-0004)
- Failures can be traced through application code and the two underlying libraries
- No version coupling between the framework and its underlying libraries
- The small dependency surface makes the package behavior easier to inspect

### Negative
- No pre-built Bear loader; this repository owns `bear_reader.py`
- No pre-built Markdown strategy; this repository owns `chunker.py`
- If the pipeline grew to 10+ stages with complex routing, a framework would reduce boilerplate

### Neutral
- The code we wrote instead of using framework abstractions is itself instructive and easy to test
