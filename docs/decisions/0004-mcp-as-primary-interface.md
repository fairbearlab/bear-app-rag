---
title: "ADR-0004: MCP as Primary Interface"
---

# ADR-0004: MCP as Primary Interface

Status: Accepted
Date: 2026-03-26
Context: Phase 2 (MCP server design)

## Context

bear-app-rag started as a CLI tool (`bear-rag ask "question"`). But the real value is letting AI agents search your notes during conversations, not running CLI commands yourself. The question: what interface should AI agents use?

## Decision

Build an MCP (Model Context Protocol) server as the primary interface. The CLI remains for admin tasks (index, sync, status) and debugging.

The MCP server exposes 6 tools: `search_notes`, `read_note`, `list_notes`, `list_tags`, `sync_notes`, and `status`. Each tool has carefully written descriptions that serve as UX copy for AI agents. The descriptions explain what the tool does, when to use it, and what the return format looks like.

The server runs over stdio (local-only, no network transport) and reads the Bear database in read-only mode (`?mode=ro`).

## Alternatives Considered

**REST API:** Standard, well-understood. But requires a running server process, port management, and authentication. Adds operational complexity for what's fundamentally a local tool. AI agents like Claude Code can't natively call REST endpoints during conversation.

**GraphQL:** Flexible querying but heavyweight for 6 operations. Same server-process concerns as REST.

**CLI wrapping (agent calls `bear-rag ask` via subprocess):** Works but loses structured data. The agent gets a string back instead of typed results with metadata. No support for streaming or tool-specific error handling.

**Direct library import:** The agent imports `bear_rag` as a Python module. Tightest coupling, fastest, but requires the agent to run Python and manage dependencies. Not portable across agent runtimes.

## Consequences

### Positive
- Claude Code (and any MCP-compatible agent) can search notes natively during conversation
- stdio transport means zero network config, zero auth, zero port conflicts
- Tool descriptions guide agents to use the right tool for each task
- Structured JSON returns with citation metadata (note PK, title, tags, heading path)

### Negative
- MCP is a newer protocol with a smaller ecosystem than REST
- Agents that don't support MCP can't use the server directly
- stdio transport means one server per agent session (no shared service)

### Neutral
- The CLI still works for all operations, so MCP is additive, not a migration
