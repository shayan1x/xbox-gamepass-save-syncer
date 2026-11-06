"""Fake Xbox save folders, written byte by byte in the real format (not with gss's own writer)."""

import io
import shutil
import struct
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from gss import cli, wgs
from gss.accounts import user_dir_name

PKG = "BethesdaSoftworks.ProjectTitan_3275kfvn8vcwc"  # DOOM: The Dark Ages, in games.json
SCID = "00000000000000000000000071672517"
XUID_A = 2535412345678901
XUID_B = 2535498765432109
FILETIME = 133000000000000000

SAVE_A = {
    "GAME-AUTOSAVE1": {"game.details": b"A details", "game_duration.dat": b"A" * 5000},
    "PROFILE": {"profile.bin": b"A profile"},
}
SAVE_B = {
    "GAME-AUTOSAVE1": {"game.details": b"B details", "game_duration.dat": b"B" * 100},
    "PROFILE": {"profile.bin": b"B profile"},
}


def utf16(s: str) -> bytes:
    return struct.pack("<i", len(s)) + s.encode("utf-16-le")


def write_user_dir(path: Path, containers: dict, etags: dict | None = None, states: dict | None = None,
                   package: str = PKG, sync_flags: int = 3) -> None:
    """Write a save folder as Xbox leaves it after a sync.

    containers: {container name: {file name: bytes}}. Each container gets a random cloud ETag
    unless `etags` gives one, and state 1 (synced) unless `states` gives one."""
    path.mkdir(parents=True)
    index = struct.pack("<ii", 14, len(containers)) + utf16("") + utf16(f"{package}!Game")
    index += struct.pack("<QI", FILETIME, sync_flags) + utf16(str(uuid.uuid4())) + struct.pack("<Q", 0x10000000)
    for num, (cname, files) in enumerate(containers.items(), start=1):
        cguid = uuid.uuid4()
        etag = (etags or {}).get(cname, f'"0x{uuid.uuid4().hex[:15].upper()}"')
        state = (states or {}).get(cname, 1)
        index += utf16(cname) + utf16(cname) + utf16(etag)
        index += struct.pack("<B", num) + struct.pack("<I", state) + cguid.bytes_le
        index += struct.pack("<QIIQ", FILETIME, 0, 0, sum(len(d) for d in files.values()))

        cdir = path / cguid.hex.upper()
        cdir.mkdir()
        blob = struct.pack("<ii", 4, len(files))
        for fname, data in files.items():
            fguid = uuid.uuid4()
            blob += fname.encode("utf-16-le").ljust(128, b"\0") + fguid.bytes_le * 2
            (cdir / fguid.hex.upper()).write_bytes(data)
        (cdir / f"container.{num}").write_bytes(blob)
    (path / "containers.index").write_bytes(index)


def snapshot(path: Path) -> dict:
    """Every file under path, for checking that nothing changed."""
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def saves(path: Path) -> dict:
    """{container: {file: bytes}}, without containers marked deleted."""
    return {c.name: {f.name: f.path.read_bytes() for f in c.files} for c in wgs.read_saves(path)}


class FakePackages(unittest.TestCase):
    """A Packages folder with DOOM: The Dark Ages saves for accounts A and B."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "Packages"
        self.wgs = self.root / PKG / "SystemAppData" / "wgs"
        self.dir_a = self.wgs / user_dir_name(XUID_A, SCID)
        self.dir_b = self.wgs / user_dir_name(XUID_B, SCID)
        write_user_dir(self.dir_a, SAVE_A)
        write_user_dir(self.dir_b, SAVE_B)
        (self.wgs / "t").mkdir()
        self.out = self.tmp / "backups"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def gss(self, *args) -> tuple[int, str, str]:
        """Run the gss command; returns (exit code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["--packages-root", str(self.root), *map(str, args)])
        return code, out.getvalue(), err.getvalue()

    def run_gss(self, *args) -> int:
        return self.gss(*args)[0]

    def backups(self):
        return sorted(self.out.glob("*.zip"))

    def backup_of(self, xuid) -> Path:
        before = set(self.backups())
        self.assertEqual(self.run_gss("backup", "--user", xuid, "-o", self.out), 0)
        [new] = set(self.backups()) - before
        return new

    def add_game(self, package: str, xuid: int = XUID_A, containers: dict = SAVE_A) -> Path:
        path = self.root / package / "SystemAppData" / "wgs" / user_dir_name(xuid, SCID)
        write_user_dir(path, containers, package=package)
        return path
