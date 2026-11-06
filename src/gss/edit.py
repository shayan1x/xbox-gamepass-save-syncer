"""Shared steps for changing an account's saves in a way Xbox cloud sync accepts.

Changes are built in a separate folder from the account's current index, then swapped in:
    1. read the account's index (refusing a half-synced folder)
    2. build the new folder: new or changed containers, plus deletion markers
    3. write an index that keeps the account's sync identity, is newer than the old one and is
       no longer marked fully uploaded, so Xbox pushes the changes on the next sync
    4. back up the current folder, swap the new one in, check it, and roll back on any failure
"""

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from gss import GssError
from gss.backup import create_backup, extract_backup, read_backup
from gss.discovery import UserSave
from gss.fsutil import remove_tree
from gss.wgs import (
    INDEX_FULLY_UPLOADED,
    INDEX_NAME,
    SYNC_DELETED,
    Container,
    WgsIndex,
    blob_path,
    filetime_now,
    index_bytes,
    read_index,
    save_contents,
)


@dataclass
class Change:
    save: str
    action: str  # "replace", "add", "delete", "remove" or "keep"

    def describe(self) -> str:
        return {
            "replace": "replaced, uploaded to the cloud",
            "add": "added, uploaded to the cloud",
            "delete": "deleted, also from the cloud",
            "remove": "deleted (it was never uploaded)",
            "keep": "kept as it is",
        }[self.action]


def read_current(user_dir: Path) -> WgsIndex:
    """The account's current index, with a clear message if Xbox is in the middle of a sync."""
    try:
        return read_index(user_dir)
    except GssError as e:
        raise GssError(
            "The account's saves are incomplete, probably because Xbox is still syncing them or "
            f"the game is running ({e}). Close the game, wait a minute, and try again."
        ) from e


def next_mtime(*indexes: WgsIndex) -> int:
    """A timestamp later than now and than every given index."""
    return max([filetime_now()] + [i.mtime + 1 for i in indexes])


def copy_container(source_dir: Path, container: Container, out: Path) -> None:
    """Copy a container's file and the data files of its blobs, unchanged."""
    cfile = source_dir / container.folder / container.file_name
    if not cfile.exists():
        return
    (out / container.folder).mkdir(exist_ok=True)
    shutil.copyfile(cfile, out / container.folder / cfile.name)
    for b in container.blobs:
        p = blob_path(source_dir, container, b)
        if p is not None:
            shutil.copyfile(p, out / container.folder / p.name)


def delete_container(source_dir: Path, container: Container, out: Path) -> Tuple[Container | None, Change | None]:
    """Delete a container: a marker if the cloud has it, so the deletion syncs; nothing otherwise.

    Returns the index entry to keep (or None) and the change to report (or None if it was
    already deleted)."""
    if container.etag == "":
        return None, Change(container.name, "remove")
    copy_container(source_dir, container, out)
    marker = Container(**{**container.__dict__, "state": SYNC_DELETED, "blobs": list(container.blobs)})
    change = None if container.state == SYNC_DELETED else Change(container.name, "delete")
    return marker, change


def write_index(current: WgsIndex, containers: List[Container], out: Path, mtime: int) -> None:
    """Write the new index: the account's own sync identity, with the changes marked for upload."""
    index = WgsIndex(
        version=current.version,
        unknown=current.unknown,
        aumid=current.aumid,
        mtime=mtime,
        sync_flags=current.sync_flags & ~INDEX_FULLY_UPLOADED,
        owner_id=current.owner_id,
        quota=current.quota,
        containers=sorted(containers, key=lambda c: c.name),
    )
    (out / INDEX_NAME).write_bytes(index_bytes(index))


def swap_in(
    save: UserSave,
    prepared: Path,
    expected: Dict[Tuple[str, str], str],
    names: Dict[str, str],
    safety_dir: Path,
    label: str,
) -> Path:
    """Back up the account's current saves, replace them with `prepared`, and check the result.

    Puts the previous saves back if anything goes wrong. Returns the safety backup's path."""
    safety = create_backup(save, safety_dir, names, label=label)
    try:
        remove_tree(save.path)
        shutil.copytree(prepared, save.path)
        if save_contents(save.path) != expected:
            raise GssError("the saves on disk don't match what was written")
    except Exception as e:
        if save.path.exists():
            remove_tree(save.path)
        extract_backup(read_backup(safety.path), save.path)
        raise GssError(f"Failed, the previous saves were put back: {e}") from e
    return safety.path
