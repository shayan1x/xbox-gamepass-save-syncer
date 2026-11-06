"""Resetting a game's saves for one Xbox account, so the game starts from the beginning.

Deleting the save files isn't enough: Xbox would see them as missing locally and download the
cloud copy again. Instead each save the cloud has is marked deleted, keeping its cloud ETag, and
Xbox deletes the cloud copy on the next sync. Saves that were never uploaded are just removed.
"""

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List

from gss import GssError
from gss.discovery import UserSave
from gss.edit import Change, copy_container, delete_container, next_mtime, read_current, swap_in, write_index
from gss.restore import DEFAULT_BACKUP_DIR
from gss.wgs import SYNC_DELETED, Container, save_contents


@dataclass
class ResetPreview:
    save: UserSave
    changes: List[Change] = field(default_factory=list)


@dataclass
class ResetResult:
    target_dir: Path
    safety_backup: Path
    changes: List[Change]


def build_reset_saves(target: Path, out: Path, only: Iterable[str] | None = None) -> List[Change]:
    """Write a copy of the saves in `target` into `out`, with the selected saves deleted.

    only: names of the saves to delete; all of them if None. The others are kept as they are."""
    current = read_current(target)
    live = [c.name for c in current.containers if c.state != SYNC_DELETED]
    selected = set(live) if only is None else set(only)
    unknown = selected - set(live)
    if unknown:
        raise GssError(
            f"No save named {', '.join(sorted(unknown))}. The saves are: {', '.join(live) or '(none)'}"
        )
    if not selected:
        raise GssError("There are no saves to reset")

    out.mkdir(parents=True)
    containers: List[Container] = []
    changes: List[Change] = []
    for c in current.containers:
        if c.name in selected:
            marker, change = delete_container(target, c, out)
            if marker is not None:
                containers.append(marker)
            changes.append(change)
        else:
            copy_container(target, c, out)
            containers.append(c)
            if c.state != SYNC_DELETED:
                changes.append(Change(c.name, "keep"))

    write_index(current, containers, out, next_mtime(current))
    return changes


def reset_saves(
    save: UserSave,
    names: Dict[str, str],
    only: Iterable[str] | None = None,
    safety_dir: Path = DEFAULT_BACKUP_DIR,
    confirm: Callable[[ResetPreview], bool] = lambda preview: True,
) -> ResetResult:
    """Reset an account's saves for a game. confirm() sees what will change and can still cancel.

    The saves are backed up to safety_dir first, and put back if anything fails."""
    only = list(only) if only else None
    with tempfile.TemporaryDirectory(prefix="gss-") as tmp:
        prepared = Path(tmp) / "prepared"
        changes = build_reset_saves(save.path, prepared, only)
        kept = {ch.save for ch in changes if ch.action == "keep"}
        expected = {k: v for k, v in save_contents(save.path).items() if k[0] in kept}
        if save_contents(prepared) != expected:
            raise GssError("Internal error: the prepared saves aren't as expected. Nothing was changed.")

        if not confirm(ResetPreview(save, changes)):
            raise GssError("Cancelled, nothing was changed")

        safety = swap_in(save, prepared, expected, names, safety_dir, "before_reset")
    return ResetResult(save.path, safety, changes)
