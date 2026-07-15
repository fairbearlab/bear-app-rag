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

Use the MIT license. It permits reuse with a short, familiar attribution requirement.

## Alternatives Considered

**Apache 2.0:** Includes an explicit patent grant and additional terms. Those protections are
useful in some projects, but the shorter MIT terms fit this small developer tool.

**GPL/AGPL:** Copyleft keeps derivative work open. That is a valid goal, but it would impose
conditions on integrations that this project does not need.

**No license (public domain / Unlicense):** Some jurisdictions don't recognize public domain dedications. MIT is universally understood by corporate legal teams.

## Consequences

### Positive
- Compatible with commercial and private use under familiar terms
- Standard for developer tools and CLI utilities
- Common enough that users can understand the obligation quickly

### Negative
- No patent protection (acceptable: no patentable techniques in this project)
- No copyleft: someone could fork and close-source it (acceptable: the portfolio value is in the original repo, not in preventing forks)

### Neutral
- The all-MiniLM-L6-v2 embedding model bundled by ChromaDB is Apache 2.0 licensed, which is compatible with MIT. The model license is separate from the repo license. Users redistributing the model should note its Apache 2.0 terms.
