"""Reading and writing the Xbox "wgs" (Connected Storage) save format.

Each Xbox account's saves for a game live in
%LOCALAPPDATA%\\Packages\\<package>\\SystemAppData\\wgs\\<XUID>_<SCID>\\.

Layout from https://github.com/xodus-gaming/xodus/wiki/savefileformat, checked against real
saves. Strings are a uint32 character count followed by UTF-16LE. GUIDs are stored as in
uuid.bytes_le.

containers.index: uint32 version (14), uint32 entry count, string (unknown, usually empty),
  string AUMID ("<package>!<app>"), FILETIME last modified, uint32 sync flags,
  string ownerChangedID, uint64 storage quota, then one entry per container:
  string name, string display name, string ETag, uint8 container number, uint32 sync state,
  GUID container folder, FILETIME last modified, uint32 flags, uint32 unknown, uint64 total size.

<container GUID>/container.<number>: uint32 version (4), uint32 blob count, then per blob:
  128 bytes UTF-16LE name, GUID last synced atom, GUID current atom. A blob's data is the file
  named after one of its atoms. Atom GUIDs are shared with the cloud.

How Xbox cloud sync uses this: the ETag is the cloud version a container was last synced at. A
"synced" container whose ETag differs from the cloud's is treated as out of date and downloaded
again. Local data only wins if the container keeps the cloud's ETag and is marked "modified",
with changed blobs given a new current atom while the last synced atom stays the cloud's.
"""

import struct
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from gss import GssError
from gss.fsutil import sha256_file

SYNC_SYNCED = 1
SYNC_MODIFIED = 2
SYNC_DELETED = 3
SYNC_CREATED = 5
INDEX_FULLY_UPLOADED = 1
ZERO_GUID = uuid.UUID(int=0)
INDEX_NAME = "containers.index"
FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


@dataclass
class Blob:
    name: str
    synced_atom: uuid.UUID
    current_atom: uuid.UUID


@dataclass
class Container:
    name: str
    display_name: str
    etag: str
    number: int
    state: int
    guid: uuid.UUID
    mtime: int
    flags: int
    unknown: int
    size: int
    file_version: int = 4
    blobs: List[Blob] = field(default_factory=list)

    @property
    def folder(self) -> str:
        return self.guid.hex.upper()

    @property
    def file_name(self) -> str:
        return f"container.{self.number}"


@dataclass
class WgsIndex:
    version: int
    unknown: str
    aumid: str
    mtime: int
    sync_flags: int
    owner_id: str
    quota: int
    containers: List[Container]

    @property
    def package(self) -> str:
        return self.aumid.split("!")[0]


@dataclass
class SaveFile:
    name: str
    path: Path


@dataclass
class SaveContainer:
    """A container with the paths of its files' data, ready to be read."""

    name: str
    files: List[SaveFile]


# ---------------------------------------------------------------- reading


def _read_str(f) -> str:
    (n,) = _unpack(f, "<I")
    data = f.read(n * 2)
    if len(data) != n * 2:
        raise ValueError("unexpected end of file")
    return data.decode("utf-16-le")


def _unpack(f, fmt: str):
    size = struct.calcsize(fmt)
    data = f.read(size)
    if len(data) != size:
        raise ValueError("unexpected end of file")
    return struct.unpack(fmt, data)


def _read_guid(f) -> uuid.UUID:
    data = f.read(16)
    if len(data) != 16:
        raise ValueError("unexpected end of file")
    return uuid.UUID(bytes_le=data)


def read_index(user_dir: Path) -> WgsIndex:
    """Read containers.index and the container.N file of every container in it."""
    index_path = user_dir / INDEX_NAME
    try:
        with index_path.open("rb") as f:
            version, count = _unpack(f, "<II")
            unknown, aumid = _read_str(f), _read_str(f)
            mtime, sync_flags = _unpack(f, "<QI")
            owner_id = _read_str(f)
            (quota,) = _unpack(f, "<Q")
            containers = []
            for _ in range(count):
                name, display, etag = _read_str(f), _read_str(f), _read_str(f)
                number, state = _unpack(f, "<BI")
                guid = _read_guid(f)
                cmtime, flags, unk, size = _unpack(f, "<QIIQ")
                containers.append(Container(name, display, etag, number, state, guid, cmtime, flags, unk, size))
            if f.read(1):
                raise ValueError("unexpected data after the last container")
    except (OSError, ValueError, UnicodeDecodeError) as e:
        raise GssError(f"Can't read {index_path}: {e}") from e

    for c in containers:
        cfile = user_dir / c.folder / c.file_name
        if c.state == SYNC_DELETED and not cfile.exists():
            continue
        try:
            with cfile.open("rb") as f:
                c.file_version, blob_count = _unpack(f, "<II")
                for _ in range(blob_count):
                    raw = f.read(128)
                    if len(raw) != 128:
                        raise ValueError("unexpected end of file")
                    name = raw.decode("utf-16-le").split("\0", 1)[0]
                    c.blobs.append(Blob(name, _read_guid(f), _read_guid(f)))
        except (OSError, ValueError, UnicodeDecodeError) as e:
            raise GssError(f'Can\'t read save "{c.name}" ({cfile}): {e}') from e
    return WgsIndex(version, unknown, aumid, mtime, sync_flags, owner_id, quota, containers)


def live_containers(index: WgsIndex) -> List[Container]:
    """Containers that hold a save, i.e. not ones marked deleted."""
    return [c for c in index.containers if c.state != SYNC_DELETED]


def blob_path(user_dir: Path, container: Container, blob: Blob) -> Path | None:
    """The file with a blob's data: its current atom, or the last synced one if that's all there is."""
    for atom in (blob.current_atom, blob.synced_atom):
        path = user_dir / container.folder / atom.hex.upper()
        if atom != ZERO_GUID and path.is_file():
            return path
    return None


def read_saves(user_dir: Path) -> List[SaveContainer]:
    """Every save container in a folder, with the path of each file's data."""
    index = read_index(user_dir)
    saves = []
    for c in live_containers(index):
        files = []
        for b in c.blobs:
            path = blob_path(user_dir, c, b)
            if path is None:
                raise GssError(
                    f'The data of "{c.name}/{b.name}" is missing in {user_dir}. Xbox may still be '
                    "syncing; close the game and try again in a minute."
                )
            files.append(SaveFile(b.name, path))
        saves.append(SaveContainer(c.name, files))
    return saves


def save_contents(user_dir: Path) -> Dict[Tuple[str, str], str]:
    """{(container, file): sha256} for every save file in a folder."""
    return {(c.name, f.name): sha256_file(f.path) for c in read_saves(user_dir) for f in c.files}


# ---------------------------------------------------------------- writing


def _write_str(s: str) -> bytes:
    return struct.pack("<I", len(s)) + s.encode("utf-16-le")


def index_bytes(index: WgsIndex) -> bytes:
    out = struct.pack("<II", index.version, len(index.containers))
    out += _write_str(index.unknown) + _write_str(index.aumid)
    out += struct.pack("<QI", index.mtime, index.sync_flags)
    out += _write_str(index.owner_id) + struct.pack("<Q", index.quota)
    for c in index.containers:
        out += _write_str(c.name) + _write_str(c.display_name) + _write_str(c.etag)
        out += struct.pack("<BI", c.number, c.state) + c.guid.bytes_le
        out += struct.pack("<QIIQ", c.mtime, c.flags, c.unknown, c.size)
    return out


def container_bytes(container: Container) -> bytes:
    out = struct.pack("<II", container.file_version, len(container.blobs))
    for b in container.blobs:
        name = b.name.encode("utf-16-le")
        if len(name) > 128:
            raise GssError(f"File name too long for the save format: {b.name!r}")
        out += name.ljust(128, b"\0") + b.synced_atom.bytes_le + b.current_atom.bytes_le
    return out


def filetime_now() -> int:
    return int((datetime.now(timezone.utc) - FILETIME_EPOCH).total_seconds() * 10_000_000)


def filetime_to_datetime(filetime: int) -> datetime:
    return datetime.fromtimestamp((filetime - 116444736000000000) / 10_000_000, tz=timezone.utc)
