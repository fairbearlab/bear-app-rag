---
title: Architecture Decision Records
---

# Architecture Decision Records

These records preserve the context, alternatives, and consequences behind the project's main technical choices. Later amendments stay with the original decision when that history helps explain the current code.

| ADR | Decision | Phase |
|-----|----------|-------|
| [ADR-0001](0001-no-langchain.md) | No LangChain: direct library calls for a small pipeline | Phase 1 |
| [ADR-0002](0002-local-onnx-embeddings.md) | Local ONNX retrieval with explicit MCP and eval boundaries | Phase 1 |
| [ADR-0003](0003-chunk-sizing-strategy.md) | Markdown-aware chunking at 300 words with heading hierarchy | Phase 1 |
| [ADR-0004](0004-mcp-as-primary-interface.md) | MCP for retrieval, CLI for maintenance and demo | Phase 2 |
| [ADR-0005](0005-incremental-sync-via-timestamps.md) | Core Data timestamps for incremental sync | Phase 2 |
| [ADR-0006](0006-hand-rolled-eval-framework.md) | Hand-rolled eval with pytest, no eval framework | Phase 3 |
| [ADR-0007](0007-mit-license.md) | MIT license for permissive reuse | Phase 4 |
| [ADR-0008](0008-embedding-model-evaluation.md) | Embedding model evaluation: keep all-MiniLM-L6-v2 on the evidence | Phase 5 |
