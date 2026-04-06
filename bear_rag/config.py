from pathlib import Path

# Bear database
BEAR_DB_PATH = (
    Path.home()
    / "Library/Group Containers/9K33E3U3T4.net.shinyfrog.bear"
    / "Application Data/database.sqlite"
)

# Persistent state
DATA_DIR = Path.home() / ".bear-rag"
CHROMA_DIR = DATA_DIR / "chroma"
SYNC_STATE_PATH = DATA_DIR / "last_sync.json"

# Index schema version — bump when stored format changes (e.g. tag delimiters)
INDEX_VERSION = 2

# Chunking
MAX_CHUNK_WORDS = 300
MIN_CHUNK_WORDS = 30
OVERLAP_WORDS = 40

# Claude
CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_MAX_TOKENS = 4096
