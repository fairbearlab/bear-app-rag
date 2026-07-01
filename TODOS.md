# TODOs

## P3 — `get_stats()` O(everything) metadata scan

- **What:** `bear_rag/store.py:223-225` calls `self._collection.get(include=["metadatas"])`,
  loading all chunk metadata into memory to count unique `note_pk`s on every `status` call
  (CLI `status` and the MCP `status` tool).
- **Why:** Same O(everything) scaling smell flagged for the tag-query path, just lower
  frequency. Fine at the current corpus; loads the whole metadata set per call at thousands
  of notes.
- **Pros of fixing:** Bounded `status` latency at scale.
- **Cons:** No clean O(1) note-count in Chroma without tracking it yourself — the "fix" adds
  state (a counter maintained on upsert/delete), which is more than a tidy.
- **Context:** Either maintain a `note_pk` count incrementally on upsert/delete, or accept the
  scan and document the limit. Deferred in the 2026-06-29 architecture review (decision D5).
- **Depends on:** nothing.
