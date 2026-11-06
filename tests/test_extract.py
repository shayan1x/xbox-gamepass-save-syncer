import gzip
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from gss import GssError, extract
from gss.games import CatalogEntry, load_catalog
from gss.wgs import SaveContainer, SaveFile

from tests.fixtures import PKG, SAVE_A, XUID_A, XUID_B, FakePackages


class HandlerTest(unittest.TestCase):
    """Each Steam/Epic conversion, on containers built in a temp folder."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = self.tmp / "data"
        self.data.mkdir()
        self.work = self.tmp / "work"
        self.work.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def containers(self, spec: dict) -> list:
        out = []
        for i, (cname, files) in enumerate(spec.items()):
            save_files = []
            for j, (fname, data) in enumerate(files.items()):
                p = self.data / f"{i}_{j}"
                p.write_bytes(data)
                save_files.append(SaveFile(fname, p))
            out.append(SaveContainer(cname, save_files))
        return out

    def run_handler(self, name: str, spec: dict, **args) -> dict:
        entry = CatalogEntry("pkg", "Game", name, args)
        return {n: p.read_bytes() for n, p in extract.convert(self.containers(spec), entry, self.work)}

    def test_every_games_json_handler_exists(self):
        for entry in load_catalog().values():
            self.assertIn(entry.handler, extract.HANDLERS, entry.name)

    def test_1c1f(self):
        spec = {"slot1": {"anything": b"1"}, "slot2": {"x": b"2"}}
        self.assertEqual(self.run_handler("1c1f", spec), {"slot1": b"1", "slot2": b"2"})
        self.assertEqual(self.run_handler("1c1f", spec, suffix=".sav"), {"slot1.sav": b"1", "slot2.sav": b"2"})

    def test_1cnf(self):
        spec = {"all": {"a": b"1", "b": b"2"}, "ignored": {"c": b"3"}}
        self.assertEqual(self.run_handler("1cnf", spec), {"a": b"1", "b": b"2"})
        self.assertEqual(self.run_handler("1cnf", spec, suffix=".sos"), {"a.sos": b"1", "b.sos": b"2"})
        self.assertEqual(self.run_handler("1cnf", {}), {})

    def test_1cnf_folder(self):
        self.assertEqual(self.run_handler("1cnf-folder", SAVE_A), {
            "GAME-AUTOSAVE1/game.details": b"A details",
            "GAME-AUTOSAVE1/game_duration.dat": b"A" * 5000,
            "PROFILE/profile.bin": b"A profile",
        })

    def test_control(self):
        out = self.run_handler("control", {"save/slot1": {"state": b"s", "meta": b"m"}})
        self.assertEqual(out, {
            "save/slot1/--containerDisplayName.chunk": b"save/slot1",
            "save/slot1/state.chunk": b"s",
            "save/slot1/meta.chunk": b"m",
        })

    def test_starfield_old_format(self):
        spec = {
            "Saves/Save1.sfs": {"BETHESDAPFH": b"H" * 20, "P1P": b"two", "P0P": b"one" * 6},
            "Settings/foo": {"x": b"skip me"},
        }
        out = self.run_handler("starfield", spec)
        pad = lambda n: (b"padding\0" * 2)[: (16 - n % 16) % 16]  # noqa: E731
        self.assertEqual(out, {"Save1.sfs": b"H" * 20 + pad(20) + b"one" * 6 + pad(18) + b"two" + pad(3)})

    def test_starfield_new_format(self):
        spec = {"Saves/Save2.sfs": {"toc": b"toc", "BlobData1": b"b" * 16, "BlobData0": b"a" * 32}}
        self.assertEqual(self.run_handler("starfield", spec), {"Save2.sfs": b"a" * 32 + b"b" * 16})

    def test_lies_of_p(self):
        out = self.run_handler("lies-of-p", {"123SaveGame": {"x": b"1"}, "456": {"x": b"2"}})
        self.assertEqual(out, {"SaveGame.sav": b"1", "456.sav": b"2"})

    def test_palworld(self):
        out = self.run_handler("palworld", {"World-Players-ABC": {"x": b"1"}})
        self.assertEqual(out, {"World/Players/ABC.sav": b"1"})

    def test_like_a_dragon(self):
        spec = {
            "slot1/datasav": {"data": b"d1", "icon": b"i1"},
            "system/datasys": {"DATA": b"d2"},
            "other/thing": {"data": b"d3", "junk": b"j"},
        }
        self.assertEqual(self.run_handler("like-a-dragon", spec), {
            "slot1/data.sav": b"d1", "system/data.sys": b"d2", "other/thing": b"d3",
        })
        with_icons = self.run_handler("like-a-dragon", spec, icon_format="dds")
        self.assertEqual(with_icons["slot1/slot1_icon.dds"], b"i1")

    def test_cricket_24(self):
        self.assertEqual(self.run_handler("cricket-24", {"Career": {"save.CHUNK0": b"1", "meta": b"2"}}),
                         {"Career/save.SAV": b"1", "Career/meta.SAV": b"2"})
        with self.assertRaises(GssError):
            self.run_handler("cricket-24", {"Career": {"save.CHUNK1": b"1"}})

    def test_forza(self):
        self.assertEqual(self.run_handler("forza", {"profile": {"a": b"1", "b": b"2"}}),
                         {"profile.a": b"1", "profile.b": b"2"})

    def test_arcade_paradise(self):
        self.assertEqual(self.run_handler("arcade-paradise", {"x": {"y": b"1"}}), {"RATSaveData.dat": b"1"})

    def test_state_of_decay_2(self):
        self.assertEqual(self.run_handler("state-of-decay-2", {"c": {"Saves/Slot1": b"1", "Top": b"2"}}),
                         {"Slot1.sav": b"1", "Top.sav": b"2"})

    def test_railway_empire_2(self):
        self.assertEqual(self.run_handler("railway-empire-2", {"Game1": {"savegame": b"1", "description": b"d"}}),
                         {"Game1": b"1"})

    def test_coral_island(self):
        self.assertEqual(self.run_handler("coral-island", {"Slot1": {"x": b"1"}, "BackupSlot1": {"x": b"2"}}),
                         {"Slot1.sav": b"1", "Backup/Slot1.sav": b"2"})

    def test_one_lonely_outpost(self):
        doc = {"files": {"$values": [
            {"name": "ConsoleSaves/save1.json", "datas": {"$values": ["{\"a\": 1}"]}},
            {"name": "ConsoleSaves/sub/settings.json", "datas": {"$values": ["x"]}},
        ]}}
        out = self.run_handler("one-lonely-outpost", {"c": {"f": gzip.compress(json.dumps(doc).encode())}})
        self.assertEqual(out, {"save1.json": b"{\"a\": 1}", "sub/settings.json": b"x"})

    def test_unknown_handler(self):
        with self.assertRaisesRegex(GssError, "Unknown handler"):
            self.run_handler("nope", {})


class ExtractCommandTest(FakePackages):
    def test_extract_zip_per_account(self):
        out_dir = self.tmp / "extracted"
        self.add_game("SomePublisher.UnknownGame_abcdefghijklm")
        code, out, _ = self.gss("extract", "-o", out_dir)
        self.assertEqual(code, 0)
        zips = sorted(out_dir.glob("*.zip"))
        self.assertEqual(len(zips), 2)
        with zipfile.ZipFile(next(z for z in zips if str(XUID_A) in z.name)) as zf:
            self.assertEqual({n: zf.read(n) for n in zf.namelist()}, {
                "GAME-AUTOSAVE1/game.details": b"A details",
                "GAME-AUTOSAVE1/game_duration.dat": b"A" * 5000,
                "PROFILE/profile.bin": b"A profile",
            })
        self.assertIn(str(XUID_B), " ".join(z.name for z in zips))
        self.assertIn("Skipped", out)
        self.assertIn("SomePublisher.UnknownGame", out.split("Skipped")[1])

    def test_extract_only_unsupported_games(self):
        shutil.rmtree(self.root / PKG)
        self.add_game("SomePublisher.UnknownGame_abcdefghijklm")
        code, out, _ = self.gss("extract", "-o", self.tmp / "extracted")
        self.assertEqual(code, 1)
        self.assertIn("None of these games", out)

    def test_extract_filters(self):
        out_dir = self.tmp / "extracted"
        self.assertEqual(self.run_gss("extract", "--user", XUID_B, "-o", out_dir), 0)
        [z] = out_dir.glob("*.zip")
        self.assertIn(str(XUID_B), z.name)
