"""Where an account's saves stand with Xbox cloud sync.

Read from containers.index: each save's sync state, and the index's sync flags
(1 = everything uploaded, 2 = everything downloaded, 16 = seen during sync conflicts).
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List

from gss import GssError
from gss.wgs import (
    INDEX_FULLY_UPLOADED,
    SYNC_CREATED,
    SYNC_DELETED,
    SYNC_MODIFIED,
    SYNC_SYNCED,
    blob_path,
    filetime_to_datetime,
    read_index,
)

INDEX_FULLY_DOWNLOADED = 2
INDEX_CONFLICT = 16

# What the summary says, from best to worst
SYNCED = "synced"
PENDING = "pending"
CONFLICT = "conflict"
INCOMPLETE = "incomplete"


@dataclass
class SlotStatus:
    name: str
    state: int
    size: int
    saved: datetime | None
    data_missing: bool = False

    @property
    def pending(self) -> bool:
        return self.state in (SYNC_MODIFIED, SYNC_DELETED, SYNC_CREATED)

    def describe(self) -> str:
        if self.data_missing:
            return "data missing, Xbox may still be syncing"
        return {
            0: "on this PC only (offline)",
            SYNC_SYNCED: "synced",
            SYNC_MODIFIED: "changed, waiting for upload",
            SYNC_DELETED: "deleted, waiting to be deleted in the cloud",
            SYNC_CREATED: "new, waiting for upload",
        }.get(self.state, f"unknown sync state {self.state}")


@dataclass
class SaveStatus:
    summary: str  # SYNCED, PENDING, CONFLICT or INCOMPLETE
    message: str
    slots: List[SlotStatus] = field(default_factory=list)
    last_synced: datetime | None = None

    @property
    def slot_names(self) -> List[str]:
        """Save slots that hold a save, i.e. the names reset --save takes."""
        return [s.name for s in self.slots if s.state != SYNC_DELETED]


def save_status(user_dir: Path) -> SaveStatus:
    """The sync status of one account's saves for one game. Never raises for damaged saves."""
    try:
        index = read_index(user_dir)
    except GssError as e:
        return SaveStatus(
            INCOMPLETE,
            "Incomplete: the saves can't be read right now. The game may be running or Xbox may be "
            f"syncing; close the game and check again in a minute. ({e})",
        )

    slots = []
    for c in index.containers:
        missing = c.state != SYNC_DELETED and any(blob_path(user_dir, c, b) is None for b in c.blobs)
        slots.append(SlotStatus(c.name, c.state, c.size, filetime_to_datetime(c.mtime) if c.mtime else None, missing))
    last = filetime_to_datetime(index.mtime) if index.mtime else None

    if any(s.data_missing for s in slots):
        return SaveStatus(INCOMPLETE, "Incomplete: some save data is missing. The game may be running or "
                          "Xbox may be syncing; close the game and check again in a minute.", slots, last)
    if index.sync_flags & INDEX_CONFLICT:
        return SaveStatus(CONFLICT, "Xbox may have found a sync conflict. Start the game on this account; if "
                          "Xbox asks which save to keep, choose the one you want.", slots, last)
    if any(s.pending for s in slots) or not index.sync_flags & INDEX_FULLY_UPLOADED:
        return SaveStatus(PENDING, "Not everything is uploaded yet. Start the game on this account and quit "
                          "it normally to sync with the cloud.", slots, last)
    if not index.sync_flags & INDEX_FULLY_DOWNLOADED:
        return SaveStatus(PENDING, "Not everything is downloaded yet. Start the game on this account to sync "
                          "with the cloud.", slots, last)
    return SaveStatus(SYNCED, "Everything is synced with the cloud.", slots, last)
