import shutil
import struct
import uuid

from gss import GssError, wgs
from gss.accounts import parse_xuid, split_user_dir_name, user_dir_name

from tests.fixtures import SAVE_A, SCID, XUID_A, FakePackages, saves, write_user_dir


class WgsFormatTest(FakePackages):
    def test_index_round_trips_byte_for_byte(self):
        index = wgs.read_index(self.dir_a)
        self.assertEqual(wgs.index_bytes(index), (self.dir_a / "containers.index").read_bytes())
        for c in index.containers:
            self.assertEqual(wgs.container_bytes(c), (self.dir_a / c.folder / c.file_name).read_bytes())

    def test_index_fields(self):
        index = wgs.read_index(self.dir_a)
        self.assertEqual(index.version, 14)
        self.assertEqual(index.package, "BethesdaSoftworks.ProjectTitan_3275kfvn8vcwc")
        self.assertEqual(index.sync_flags, 3)
        self.assertEqual(index.quota, 0x10000000)
        self.assertEqual([c.name for c in index.containers], ["GAME-AUTOSAVE1", "PROFILE"])
        self.assertEqual([c.state for c in index.containers], [wgs.SYNC_SYNCED] * 2)
        self.assertEqual(index.containers[0].size, 5009)
        self.assertEqual([b.name for b in index.containers[0].blobs], ["game.details", "game_duration.dat"])

    def test_read_saves(self):
        self.assertEqual(saves(self.dir_a), SAVE_A)

    def test_current_atom_is_preferred(self):
        # A blob being modified: the last synced atom's file is gone or older, the current one is newer
        index = wgs.read_index(self.dir_a)
        c = index.containers[1]
        b = c.blobs[0]
        new_atom = uuid.uuid4()
        (self.dir_a / c.folder / new_atom.hex.upper()).write_bytes(b"newer profile")
        b.current_atom = new_atom
        (self.dir_a / c.folder / c.file_name).write_bytes(wgs.container_bytes(c))
        self.assertEqual(saves(self.dir_a)["PROFILE"]["profile.bin"], b"newer profile")
        # If only the last synced atom's file exists, that's used
        (self.dir_a / c.folder / new_atom.hex.upper()).unlink()
        self.assertEqual(saves(self.dir_a)["PROFILE"]["profile.bin"], b"A profile")

    def test_deleted_containers_are_not_saves(self):
        shutil.rmtree(self.dir_a)
        write_user_dir(self.dir_a, {**SAVE_A, "OLD": {"x": b"gone"}}, states={"OLD": wgs.SYNC_DELETED})
        self.assertEqual(saves(self.dir_a), SAVE_A)
        self.assertEqual(len(wgs.read_index(self.dir_a).containers), 3)

    def test_damaged_folders_are_reported(self):
        index_bytes = (self.dir_a / "containers.index").read_bytes()
        (self.dir_a / "containers.index").write_bytes(index_bytes[:-5])
        with self.assertRaisesRegex(GssError, "Can't read"):
            wgs.read_index(self.dir_a)
        (self.dir_a / "containers.index").write_bytes(index_bytes + b"x")
        with self.assertRaisesRegex(GssError, "unexpected data"):
            wgs.read_index(self.dir_a)
        (self.dir_a / "containers.index").write_bytes(index_bytes)

        c = wgs.read_index(self.dir_a).containers[0]
        (self.dir_a / c.folder / c.blobs[0].current_atom.hex.upper()).unlink()
        with self.assertRaisesRegex(GssError, "still"):
            wgs.read_saves(self.dir_a)
        (self.dir_a / c.folder / c.file_name).unlink()
        with self.assertRaisesRegex(GssError, "GAME-AUTOSAVE1"):
            wgs.read_index(self.dir_a)

    def test_filetime(self):
        self.assertEqual(wgs.filetime_to_datetime(116444736000000000).timestamp(), 0)
        now = wgs.filetime_now()
        self.assertLess(abs(wgs.filetime_to_datetime(now).timestamp() - __import__("time").time()), 5)

    def test_long_blob_names_are_refused(self):
        c = wgs.read_index(self.dir_a).containers[0]
        c.blobs[0].name = "x" * 65
        with self.assertRaises(GssError):
            wgs.container_bytes(c)


class AccountsTest(FakePackages):
    def test_parse_xuid_formats(self):
        for text in ["2535412345678901", "000901F1B0392C35", "0x000901F1B0392C35", "000901f1b0392c35", " 2535412345678901 "]:
            self.assertEqual(parse_xuid(text), XUID_A, text)
        for bad in ["", "abc xyz", "0", "-5", "0x"]:
            with self.assertRaises(ValueError):
                parse_xuid(bad)

    def test_folder_names(self):
        self.assertEqual(user_dir_name(XUID_A, SCID), "000901F1B0392C35_" + SCID)
        self.assertEqual(split_user_dir_name("000901F1B0392C35_" + SCID), (XUID_A, SCID))
        for bad in ["t", "000901F1B0392C35", "short_123", "000901F1B0392C35_zz", "a_b_c"]:
            self.assertIsNone(split_user_dir_name(bad), bad)

    def test_gamertag_of_signed_in_account(self):
        from gss.accounts import XBOX_APP_PACKAGE, gamertag
        path = self.root / XBOX_APP_PACKAGE / "LocalState"
        path.mkdir(parents=True)
        (path / "XboxLiveGamer.xml").write_text(f'{{"XboxUserId": {XUID_A}, "Gamertag": "Slayer"}}')
        self.assertEqual(gamertag(XUID_A, self.root), "Slayer")
        self.assertIsNone(gamertag(12345, self.root))
        code, out, _ = self.gss("list", "--backups", self.out)
        self.assertRegex(out, rf"{XUID_A}\s+000901F1B0392C35\s+Slayer")
