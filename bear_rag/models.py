from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict


class ChunkMetadata(TypedDict):
    note_pk: int
    title: str
    tags: str
    chunk_index: int
    heading_path: str
    modified_at: str
    source: str


@dataclass
class BearNote:
    pk: int
    title: str
    text: str
    modified_at: datetime
    tags: list[str]
    is_trashed: bool
    is_archived: bool


@dataclass
class Chunk:
    id: str
    text: str
    metadata: ChunkMetadata


@dataclass
class SyncResult:
    notes_updated: int
    notes_deleted: int
    chunks_added: int
