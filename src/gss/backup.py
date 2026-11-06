"""Backups: a ZIP with a raw copy of one account's save folder for one game.

Layout:
    manifest.json   package, SCID, XUID, game name, and a SHA-256 for every file
    wgs/...         the save folder as it was on disk

The format is the same as swapper.py's, so its backups can be restored too.
"""

import hashlib
import json
import os
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from gss import GssError, __version__
from gss.accounts import user_dir_name
from gss.discovery import UserSave
from gss.fsutil import list_files, safe_relpath, sha256_file, slugify, unique_path
from gss.games import fallback_name
from gss.wgs import INDEX_NAME, read_saves

FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
WGS_PREFIX = "wgs/"


@dataclass
class Backup:
    path: Path
    manifest: Dict[str, Any]

    @property
    def package(self) -> str:
        return self.manifest["package"]

    @property
    def game(self) -> str:
        return self.manifest.get("game") or fallback_name(self.package)

    @property
    def xuid(self) -> int:
        """The account the backup restores to by default."""
        return self.manifest["xuid"]

    @property
    def source_xuid(self) -> int:
        """The account the saves were backed up from."""
        return self.manifest.get("source_xuid", self.manifest["xuid"])

    @property
    def created(self) -> datetime | None:
        try:
            return datetime.fromisoformat(self.manifest["created"])
        except (KeyError, ValueError):
            return None

    @property
    def save_names(self) -> List[str]:
        return [c["name"] for c in self.manifest.get("containers", [])]


def check_tree_matches(root: Path, expected: Dict[str, Any]) -> None:
    actual = list_files(root)
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing or extra:
        raise GssError(f"Files changed in {root}: missing={missing} new={extra}")
    for rel, meta in expected.items():
        if sha256_file(actual[rel]) != meta["sha256"]:
            raise GssError(f"{rel} changed in {root}")


def create_backup(
    save: UserSave,
    out_dir: Path,
    names: Dict[str, str],
    to_xuid: int | None = None,
    label: str = "",
) -> Backup:
    """Back up one account's saves for one game into out_dir and check the result.

    to_xuid makes the backup restore to another account by default."""
    try:
        saves = read_saves(save.path)
    except GssError as e:
        raise GssError(f"The saves are incomplete, so they weren't backed up: {e}") from e

    target_xuid = to_xuid if to_xuid is not None else save.xuid
    game = names.get(save.package)
    files = list_files(save.path)
    manifest = {
        "format": FORMAT_VERSION,
        "tool": f"gamepass-save-syncer {__version__}",
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "package": save.package,
        "game": game,
        "scid": save.scid,
        "xuid": target_xuid,
        "source_xuid": save.xuid,
        "user_dir": user_dir_name(target_xuid, save.scid),
        "containers": [{"name": c.name, "files": [f.name for f in c.files]} for c in saves],
        "files": {rel: {"size": p.stat().st_size, "sha256": sha256_file(p)} for rel, p in files.items()},
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    name = f"{slugify(game or fallback_name(save.package))}_{target_xuid}"
    if target_xuid != save.xuid:
        name += f"_from_{save.xuid}"
    if label:
        name += f"_{label}"
    out_path = unique_path(out_dir / f"{name}_{stamp}.zip")
    partial = out_path.with_name(out_path.name + ".partial")

    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
        for rel, p in files.items():
            zf.write(p, WGS_PREFIX + rel)

    # The files mustn't have changed while being read, and the ZIP must read back correctly
    try:
        check_tree_matches(save.path, manifest["files"])
        read_backup(partial)
    except GssError as e:
        partial.unlink(missing_ok=True)
        raise GssError(f"The backup didn't check out, maybe the game is running: {e}") from e
    partial.replace(out_path)
    return Backup(out_path, manifest)


def read_backup(zip_path: Path) -> Backup:
    """Open a backup and check its manifest and every file's checksum."""
    if not zip_path.is_file():
        raise GssError(f"Backup not found: {zip_path}")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            bad = zf.testzip()
            if bad is not None:
                raise GssError(f"Damaged file in backup: {bad}")
            try:
                manifest = json.loads(zf.read(MANIFEST_NAME))
            except KeyError:
                raise GssError(f"{zip_path.name} is not a gss backup (no {MANIFEST_NAME})") from None
            if manifest.get("format") != FORMAT_VERSION:
                raise GssError(f"Unsupported backup format: {manifest.get('format')!r}")
            for key in ("package", "scid", "xuid", "files"):
                if key not in manifest:
                    raise GssError(f"Backup manifest is missing {key!r}")
            int(manifest["scid"], 16)

            entries = {
                safe_relpath(n[len(WGS_PREFIX):])
                for n in zf.namelist()
                if n.startswith(WGS_PREFIX) and not n.endswith("/")
            }
            for rel in manifest["files"]:
                safe_relpath(rel)
            if entries != set(manifest["files"]):
                raise GssError("Backup contents don't match its manifest")
            if INDEX_NAME not in entries:
                raise GssError(f"Backup has no {INDEX_NAME}")
            for rel, meta in manifest["files"].items():
                if hashlib.sha256(zf.read(WGS_PREFIX + rel)).hexdigest() != meta["sha256"]:
                    raise GssError(f"Checksum mismatch for {rel} in backup")
    except zipfile.BadZipFile as e:
        raise GssError(f"{zip_path.name} is not a valid ZIP file: {e}") from e
    except (ValueError, TypeError) as e:
        raise GssError(f"{zip_path.name} has an invalid manifest: {e}") from e
    return Backup(zip_path, manifest)


def extract_backup(backup: Backup, dest: Path) -> None:
    """Unpack the save folder from a backup into dest, keeping file times."""
    with zipfile.ZipFile(backup.path) as zf:
        for rel in backup.manifest["files"]:
            info = zf.getinfo(WGS_PREFIX + rel)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            mtime = datetime(*info.date_time).timestamp()
            os.utime(target, (mtime, mtime))
