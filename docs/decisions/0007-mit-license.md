---
title: "ADR-0007: MIT License"
---

# ADR-0007: MIT License

Status: Accepted
Date: 2026-04-07
Context: Phase 4 (distribution)

## Context

The project needs a license before publishing. Without one, the code is technically "all rights reserved" regardless of being on a public GitHub repo.

## Decision

MIT license. Maximum permissiveness for a developer tool.

## Alternatives Considered

**Apache 2.0:** Includes a patent grant clause, which MIT lacks. Relevant for projects with novel algorithms or standards-track implementations. bear-app-rag doesn't contain patentable techniques, so the patent clause adds legal complexity without practical benefit.

**GPL/AGPL:** Copyleft ensures derivative works stay open. But it discourages commercial adoption and makes integration with proprietary tools awkward. For a developer tool intended as portfolio signal, maximum adoption matters more than copyleft protection.

**No license (public domain / Unlicense):** Some jurisdictions don't recognize public domain dedications. MIT is universally understood by corporate legal teams.

## Consequences

### Positive
- Compatible with commercial use, no friction for adoption
- Standard for developer tools and CLI utilities
- One of the most recognized licenses, corporate legal teams approve it routinely

### Negative
- No patent protection (acceptable: no patentable techniques in this project)
- No copyleft: someone could fork and close-source it (acceptable: the portfolio value is in the original repo, not in preventing forks)

### Neutral
- The all-MiniLM-L6-v2 embedding model bundled by ChromaDB is Apache 2.0 licensed, which is compatible with MIT. The model license is separate from the repo license. Users redistributing the model should note its Apache 2.0 terms.
