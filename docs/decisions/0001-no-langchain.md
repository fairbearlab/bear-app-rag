---
title: "ADR-0001: No LangChain"
---

# ADR-0001: No LangChain

Status: Accepted
Date: 2026-03-25
Context: Phase 1 (initial design)

## Context

Every "RAG from scratch" tutorial uses LangChain. It's the default choice for anything involving embeddings, vector stores, and LLM orchestration. Starting a RAG project without it requires justification.

We evaluated LangChain for the Bear notes pipeline and found a mismatch between what we need and what it provides.

## Decision

Build the RAG pipeline with direct library calls (chromadb, anthropic) instead of LangChain or any orchestration framework.

The entire pipeline is four operations: read SQLite, chunk text, embed into vectors, query them. For a pipeline this small, that's four libraries, not a framework.

## Alternatives Considered

**LangChain:** The obvious choice. Provides document loaders, text splitters, vector store wrappers, and chain abstractions. But it pulls in a large transitive dependency tree, wraps every library in an abstraction layer, and — for a pipeline this small — tends to turn debugging into a multi-layer stack-trace exercise where the underlying library just needed a different parameter. When ChromaDB ships a breaking change, you're waiting on LangChain to update their wrapper.

**LlamaIndex:** Similar scope to LangChain with a data-focused orientation. Same dependency and abstraction concerns.

**Haystack:** More opinionated pipeline framework. Good for complex multi-stage retrieval but overkill for a single-collection semantic search.

## Consequences

### Positive
- 4 direct dependencies total (anthropic, chromadb, mcp, python-dotenv)
- Every line of the pipeline is debuggable without framework internals
- No version coupling between the framework and its underlying libraries
- The small dependency count keeps the whole pipeline auditable in an afternoon

### Negative
- No pre-built document loaders (we wrote `bear_reader.py`, ~80 lines)
- No pre-built text splitters (we wrote `chunker.py`, ~150 lines)
- If the pipeline grew to 10+ stages with complex routing, a framework would reduce boilerplate

### Neutral
- The code we wrote instead of using framework abstractions is itself instructive and easy to test
