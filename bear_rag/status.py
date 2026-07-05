"""Index status — shared by the CLI `status` command and the MCP `status` tool.

Deliberately its own module rather than a `NoteStore` method: reading the
sync-state JSON file is presentation glue over two independent things (the
vector store's stats and `sync.py`'s state file), not something the vector
store itself needs to know about.
"""

import json

from bear_rag import config
from bear_rag.store import NoteStore


def get_status(store: NoteStore) -> dict:
    """Return index statistics plus the last-sync timestamp, if any."""
    stats = store.get_stats()

    # Fail open: a missing, unreadable, or malformed state file just means "no
    # known last-sync", never a crash. OSError covers read/permission failures;
    # ValueError covers JSON decode errors (incl. UnicodeDecodeError). The
    # isinstance guard handles valid-but-non-dict JSON (e.g. a bare list), where
    # .get would raise AttributeError.
    last_sync = None
    if config.SYNC_STATE_PATH.exists():
        try:
            state = json.loads(config.SYNC_STATE_PATH.read_text())
            if isinstance(state, dict):
                last_sync = state.get("synced_at")
        except (OSError, ValueError):
            pass

    return {
        "index_count": stats["count"],
        "note_count": stats["note_count"],
        "last_sync": last_sync,
    }
