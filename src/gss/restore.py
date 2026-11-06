"""Restoring backups, to the same Xbox account or another one.

A backup can't just be copied back: its containers.index records the cloud versions (ETags) the
saves had when it was made, maybe for another account's cloud. Xbox would see those as out of
date and download the cloud copy over the restored saves. Instead the restore rewrites the
target account's own index, so the backed-up saves look like changes made on this PC since the
last sync, which Xbox uploads the next time the game starts.
"""

import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List

from gss import GssError
from gss.accounts import split_user_dir_name, user_dir_name
from gss.backup import Backup, check_tree_matches, create_backup, extract_backup, read_backup
from gss.discovery import UserSave, wgs_dir
from gss.edit import Change, delete_container, next_mtime, read_current, swap_in, write_index
from gss.wgs import (
    INDEX_NAME,
    SYNC_CREATED,
    SYNC_MODIFIED,
    ZERO_GUID,
    Blob,
    Container,
    blob_path,
    container_bytes,
    live_containers,
    read_index,
    save_contents,
)

DEFAULT_BACKUP_DIR = Path("backups")


@dataclass
class RestorePreview:
    backup: Backup
    target_xuid: int
    target_dir: Path
    changes: List[Change] = field(default_factory=list)


@dataclass
class RestoreResult:
    target_dir: Path
    safety_backup: Path


def build_restored_saves(source: Path, target: Path, out: Path) -> List[Change]:
    """Write the saves in `source` into the new folder `out`, made to replace the saves in `target`.

    Containers keep the target's cloud ETags and are marked modified (or created, if the cloud
    doesn't have them yet), so Xbox uploads them. Containers only the target has are deleted."""
    src = read_index(source)
    tgt = read_current(target)
    if tgt.package != src.package:
        raise GssError(f"The backup is for {src.package}, but the target saves are for {tgt.package}")

    now = next_mtime(src, tgt)
    existing = {c.name: c for c in tgt.containers}
    out.mkdir(parents=True)
    containers: List[Container] = []
    changes: List[Change] = []

    for sc in live_containers(src):
        old = existing.get(sc.name)
        in_cloud = old is not None and old.etag != ""
        guid = old.guid if old is not None else uuid.uuid4()
        synced_atoms = {b.name: b.synced_atom for b in old.blobs} if in_cloud else {}
        folder = out / guid.hex.upper()
        folder.mkdir()
        blobs, size = [], 0
        for b in sc.blobs:
            data = blob_path(source, sc, b)
            if data is None:
                raise GssError(f'The backup is missing the data of "{sc.name}/{b.name}"')
            atom = uuid.uuid4()
            shutil.copyfile(data, folder / atom.hex.upper())
            size += data.stat().st_size
            # The last synced atom stays the cloud's, so Xbox sees which files changed
            blobs.append(Blob(b.name, synced_atoms.get(b.name, ZERO_GUID), atom))
        c = Container(
            name=sc.name,
            display_name=sc.display_name,
            etag=old.etag if old is not None else "",
            number=(old.number + 1) % 256 if old is not None else 1,
            state=SYNC_MODIFIED if in_cloud else SYNC_CREATED,
            guid=guid,
            mtime=now,
            flags=old.flags if old is not None else 0,
            unknown=old.unknown if old is not None else 0,
            size=size,
            file_version=sc.file_version,
            blobs=blobs,
        )
        (folder / c.file_name).write_bytes(container_bytes(c))
        containers.append(c)
        changes.append(Change(c.name, "replace" if in_cloud else "add"))

    restored = {c.name for c in containers}
    for old in tgt.containers:
        if old.name not in restored:
            marker, change = delete_container(target, old, out)
            if marker is not None:
                containers.append(marker)
            if change is not None:
                changes.append(change)

    write_index(tgt, containers, out, now)
    return changes


def restore_backup(
    zip_path: Path,
    packages_root: Path,
    names: Dict[str, str],
    to_xuid: int | None = None,
    safety_dir: Path = DEFAULT_BACKUP_DIR,
    confirm: Callable[[RestorePreview], bool] = lambda preview: True,
) -> RestoreResult:
    """Restore a backup. confirm() sees what will change and can still cancel.

    The saves being replaced are backed up to safety_dir first, and put back if anything fails."""
    backup = read_backup(zip_path)
    package = backup.package
    target_xuid = to_xuid if to_xuid is not None else backup.xuid
    if backup.manifest.get("game") and package not in names:
        names = {**names, package: backup.manifest["game"]}

    if not (packages_root / package).is_dir():
        raise GssError(f"{backup.game} is not installed ({packages_root / package} not found)")
    target = wgs_dir(packages_root, package) / user_dir_name(target_xuid, backup.manifest["scid"])
    if not (target / INDEX_NAME).is_file():
        # The restored saves have to carry this account's cloud ETags, which only its own folder has
        raise GssError(
            f"Xbox account {target_xuid} has no {backup.game} saves on this PC yet. Sign in to the "
            "Xbox app with that account, start the game once, wait until it has loaded, quit it, "
            "then restore again."
        )

    with tempfile.TemporaryDirectory(prefix="gss-") as tmp:
        staging = Path(tmp) / "backup"
        extract_backup(backup, staging)
        check_tree_matches(staging, backup.manifest["files"])
        expected = save_contents(staging)

        prepared = Path(tmp) / "prepared"
        changes = build_restored_saves(staging, target, prepared)
        if save_contents(prepared) != expected:
            raise GssError("Internal error: the prepared saves don't match the backup. Nothing was changed.")

        if not confirm(RestorePreview(backup, target_xuid, target, changes)):
            raise GssError("Cancelled, nothing was changed")

        xuid, scid = split_user_dir_name(target.name)
        safety = swap_in(UserSave(package, xuid, scid, target), prepared, expected, names, safety_dir, "before_restore")
    return RestoreResult(target, safety)


def copy_saves(
    save: UserSave,
    to_xuid: int,
    packages_root: Path,
    names: Dict[str, str],
    safety_dir: Path = DEFAULT_BACKUP_DIR,
    confirm: Callable[[RestorePreview], bool] = lambda preview: True,
) -> RestoreResult:
    """Copy one account's saves for a game to another account on this PC.

    The same as a backup of `save` restored with --to-xuid, without keeping the backup. The
    source account isn't changed; the target's saves are backed up to safety_dir first."""
    if to_xuid == save.xuid:
        raise GssError("The source and target are the same Xbox account")
    with tempfile.TemporaryDirectory(prefix="gss-copy-") as tmp:
        snapshot = create_backup(save, Path(tmp), names, to_xuid=to_xuid)
        return restore_backup(snapshot.path, packages_root, names, safety_dir=safety_dir, confirm=confirm)
