import builtins
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from gss import GssError, backup, edit, restore, wgs
from gss.accounts import user_dir_name

from tests.fixtures import (
    PKG, SAVE_A, SAVE_B, SCID, XUID_A, XUID_B, FakePackages, saves, snapshot, write_user_dir,
)


class BackupTest(FakePackages):
    def test_backup_all_accounts(self):
        self.assertEqual(self.run_gss("backup", "-o", self.out), 0)
        backups = self.backups()
        self.assertEqual({backup.read_backup(b).xuid for b in backups}, {XUID_A, XUID_B})
        self.assertFalse(list(self.out.glob("*.partial")))

    def test_backup_contents_and_manifest(self):
        path = self.backup_of(XUID_A)
        b = backup.read_backup(path)
        self.assertEqual((b.package, b.manifest["scid"], b.xuid, b.source_xuid), (PKG, SCID, XUID_A, XUID_A))
        self.assertEqual(b.game, "DOOM: The Dark Ages")
        self.assertEqual(b.save_names, ["GAME-AUTOSAVE1", "PROFILE"])
        self.assertTrue(path.name.startswith(f"doom_the_dark_ages_{XUID_A}_"))
        with zipfile.ZipFile(path) as zf:
            stored = {n[4:]: zf.read(n) for n in zf.namelist() if n.startswith("wgs/")}
        self.assertEqual(stored, snapshot(self.dir_a))

    def test_backup_filters(self):
        self.assertEqual(self.run_gss("backup", "--game", "dark ages", "--user", hex(XUID_B), "-o", self.out), 0)
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(self.run_gss("backup", "--game", "no such game", "-o", self.out), 1)

    def test_backup_skips_xbox_app_backup_folders(self):
        shutil.copytree(self.dir_a, self.wgs / (self.dir_a.name + ".backup"))
        self.assertEqual(self.run_gss("backup", "-o", self.out), 0)
        self.assertEqual(len(self.backups()), 2)

    def test_backup_refuses_incomplete_saves(self):
        c = wgs.read_index(self.dir_a).containers[0]
        (self.dir_a / c.folder / c.file_name).unlink()
        code, out, _ = self.gss("backup", "--user", XUID_A, "-o", self.out)
        self.assertEqual(code, 1)
        self.assertIn("incomplete", out)
        self.assertEqual(self.backups(), [])

    def test_to_xuid_needs_one_source_account(self):
        self.assertEqual(self.run_gss("backup", "--to-xuid", XUID_B, "-o", self.out), 1)
        self.assertEqual(self.backups(), [])

    def test_to_xuid_backup_restores_to_that_account(self):
        self.assertEqual(self.run_gss("backup", "--user", XUID_A, "--to-xuid", XUID_B, "-o", self.out), 0)
        [path] = self.backups()
        b = backup.read_backup(path)
        self.assertEqual((b.xuid, b.source_xuid), (XUID_B, XUID_A))
        self.assertIn(f"_from_{XUID_A}_", path.name)

        a_before = snapshot(self.dir_a)
        self.assertEqual(self.run_gss("restore", path, "-y", "-o", self.out), 0)
        self.assertEqual(saves(self.dir_b), SAVE_A)
        self.assertEqual(snapshot(self.dir_a), a_before)

    def test_swapper_backups_still_restore(self):
        """Backups made by swapper.py in XGP-save-extractor use the same format."""
        path = self.backup_of(XUID_A)
        legacy = self.tmp / "swapper_backup.zip"
        with zipfile.ZipFile(path) as src, zipfile.ZipFile(legacy, "w") as dst:
            for n in src.namelist():
                data = src.read(n)
                if n == "manifest.json":
                    m = json.loads(data)
                    m["tool"] = "XGP-save-extractor swapper.py"
                    data = json.dumps(m).encode()
                dst.writestr(n, data)
        self.assertEqual(self.run_gss("restore", legacy, "--to-xuid", XUID_B, "-y", "-o", self.out), 0)
        self.assertEqual(saves(self.dir_b), SAVE_A)


class RestoreTest(FakePackages):
    def test_restore_keeps_target_cloud_state_so_xbox_uploads(self):
        """Without this, Xbox downloads the cloud copy over the restored saves."""
        path = self.backup_of(XUID_A)
        b_old, a_old = wgs.read_index(self.dir_b), wgs.read_index(self.dir_a)

        self.assertEqual(self.run_gss("restore", path, "--to-xuid", XUID_B, "-y", "-o", self.out), 0)
        self.assertEqual(saves(self.dir_b), SAVE_A)
        new = wgs.read_index(self.dir_b)

        self.assertEqual(new.owner_id, b_old.owner_id)
        self.assertNotEqual(new.owner_id, a_old.owner_id)
        self.assertGreater(new.mtime, b_old.mtime)
        self.assertEqual(new.sync_flags, b_old.sync_flags & ~wgs.INDEX_FULLY_UPLOADED)
        old_by_name = {c.name: c for c in b_old.containers}
        a_etags = {c.etag for c in a_old.containers}
        for c in new.containers:
            old = old_by_name[c.name]
            self.assertEqual(c.etag, old.etag)
            self.assertNotIn(c.etag, a_etags)
            self.assertEqual(c.state, wgs.SYNC_MODIFIED)
            self.assertEqual((c.guid, c.number), (old.guid, old.number + 1))
            self.assertEqual(c.size, sum(len(d) for d in SAVE_A[c.name].values()))
            old_atoms = {b.name: b.synced_atom for b in old.blobs}
            for b in c.blobs:
                self.assertEqual(b.synced_atom, old_atoms[b.name])
                self.assertNotEqual(b.current_atom, b.synced_atom)
                self.assertTrue((self.dir_b / c.folder / b.current_atom.hex.upper()).is_file())

    def test_restore_same_account_after_playing_on(self):
        path = self.backup_of(XUID_A)
        shutil.rmtree(self.dir_a)
        write_user_dir(self.dir_a, {"GAME-AUTOSAVE1": {"game.details": b"newer"}}, etags={"GAME-AUTOSAVE1": '"0xNEWER"'})

        self.assertEqual(self.run_gss("restore", path, "-y", "-o", self.out), 0)
        self.assertEqual(saves(self.dir_a), SAVE_A)
        index = {c.name: c for c in wgs.read_index(self.dir_a).containers}
        self.assertEqual((index["GAME-AUTOSAVE1"].etag, index["GAME-AUTOSAVE1"].state), ('"0xNEWER"', wgs.SYNC_MODIFIED))
        self.assertEqual((index["PROFILE"].etag, index["PROFILE"].state), ("", wgs.SYNC_CREATED))
        self.assertEqual({b.synced_atom for b in index["PROFILE"].blobs}, {wgs.ZERO_GUID})

    def test_restore_deletes_saves_missing_from_backup(self):
        path = self.backup_of(XUID_A)
        shutil.rmtree(self.dir_b)
        write_user_dir(
            self.dir_b,
            {**SAVE_B, "GAME-AUTOSAVE2": {"game.details": b"slot 2"}, "LOCAL-ONLY": {"x": b"never uploaded"}},
            etags={"LOCAL-ONLY": ""},
            states={"LOCAL-ONLY": wgs.SYNC_CREATED},
        )
        old = {c.name: c for c in wgs.read_index(self.dir_b).containers}

        code, out, _ = self.gss("restore", path, "--to-xuid", XUID_B, "-y", "-o", self.out)
        self.assertEqual(code, 0)
        self.assertIn("GAME-AUTOSAVE2: deleted, also from the cloud", out)
        self.assertIn("LOCAL-ONLY: deleted (it was never uploaded)", out)
        index = {c.name: c for c in wgs.read_index(self.dir_b).containers}
        self.assertEqual((index["GAME-AUTOSAVE2"].state, index["GAME-AUTOSAVE2"].etag),
                         (wgs.SYNC_DELETED, old["GAME-AUTOSAVE2"].etag))
        self.assertNotIn("LOCAL-ONLY", index)
        self.assertEqual(list(index), sorted(index))
        self.assertEqual(saves(self.dir_b), SAVE_A)

    def test_restore_skips_saves_deleted_in_backup(self):
        shutil.rmtree(self.dir_a)
        write_user_dir(self.dir_a, {**SAVE_A, "OLD": {"x": b"deleted"}}, states={"OLD": wgs.SYNC_DELETED})
        path = self.backup_of(XUID_A)
        self.assertEqual(self.run_gss("restore", path, "--to-xuid", XUID_B, "-y", "-o", self.out), 0)
        self.assertEqual(saves(self.dir_b), SAVE_A)
        self.assertNotIn("OLD", {c.name for c in wgs.read_index(self.dir_b).containers})

    def test_safety_backup_undoes_a_restore(self):
        path = self.backup_of(XUID_A)
        code, out, _ = self.gss("restore", path, "--to-xuid", XUID_B, "-y", "-o", self.out)
        self.assertEqual(code, 0)
        [safety] = [b for b in self.backups() if "before_restore" in b.name]
        self.assertIn(str(safety), out)
        self.assertEqual(backup.read_backup(safety).xuid, XUID_B)
        self.assertEqual(self.run_gss("restore", safety, "-y", "-o", self.out), 0)
        self.assertEqual(saves(self.dir_b), SAVE_B)

    def test_restore_to_account_without_saves_is_refused(self):
        path = self.backup_of(XUID_A)
        new_xuid = 2535400000000001
        code, _, err = self.gss("restore", path, "--to-xuid", new_xuid, "-y", "-o", self.out)
        self.assertEqual(code, 1)
        self.assertIn("start the game once", err)
        self.assertFalse((self.wgs / user_dir_name(new_xuid, SCID)).exists())

    def test_restore_refuses_half_synced_target(self):
        path = self.backup_of(XUID_A)
        c = wgs.read_index(self.dir_b).containers[0]
        (self.dir_b / c.folder / c.file_name).unlink()
        b_before = snapshot(self.dir_b)
        code, _, err = self.gss("restore", path, "--to-xuid", XUID_B, "-y", "-o", self.out)
        self.assertEqual(code, 1)
        self.assertIn("still syncing", err)
        self.assertEqual(snapshot(self.dir_b), b_before)

    def test_saves_of_another_game_are_refused(self):
        other_dir = self.add_game("SomePublisher.OtherGame_abcdefghijklm", containers=SAVE_B)
        with self.assertRaisesRegex(GssError, "is for"):
            restore.build_restored_saves(self.dir_a, other_dir, self.tmp / "out")

    def test_cancel_changes_nothing(self):
        path = self.backup_of(XUID_A)
        b_before = snapshot(self.dir_b)
        original = builtins.input
        builtins.input = lambda *_: "n"
        try:
            self.assertEqual(self.run_gss("restore", path, "--to-xuid", XUID_B, "-o", self.out), 1)
        finally:
            builtins.input = original
        self.assertEqual(snapshot(self.dir_b), b_before)
        self.assertFalse([b for b in self.backups() if "before_restore" in b.name])

    def test_failed_copy_puts_previous_saves_back(self):
        path = self.backup_of(XUID_A)
        b_before = snapshot(self.dir_b)
        original = edit.shutil.copytree

        def broken_copytree(src, dst, *a, **kw):
            Path(dst).mkdir(parents=True)
            (Path(dst) / "partial").write_bytes(b"half")
            raise OSError("disk full")

        edit.shutil.copytree = broken_copytree
        try:
            code, _, err = self.gss("restore", path, "--to-xuid", XUID_B, "-y", "-o", self.out)
        finally:
            edit.shutil.copytree = original
        self.assertEqual(code, 1)
        self.assertIn("previous saves were put back", err)
        self.assertEqual(snapshot(self.dir_b), b_before)


class DamagedBackupTest(FakePackages):
    def tamper(self, path: Path, edit) -> Path:
        bad = path.with_name("tampered.zip")
        with zipfile.ZipFile(path) as src, zipfile.ZipFile(bad, "w") as dst:
            entries = {n: src.read(n) for n in src.namelist()}
            edit(entries)
            for n, data in entries.items():
                dst.writestr(n, data)
        return bad

    def test_changed_file_is_rejected(self):
        path = self.backup_of(XUID_A)
        b_before = snapshot(self.dir_b)

        def flip(entries):
            name = next(n for n in entries if n.startswith("wgs/") and "container." not in n and "index" not in n)
            entries[name] = b"corrupted" + entries[name]

        bad = self.tamper(path, flip)
        with self.assertRaisesRegex(GssError, "Checksum mismatch"):
            backup.read_backup(bad)
        self.assertEqual(self.run_gss("restore", bad, "--to-xuid", XUID_B, "-y", "-o", self.out), 1)
        self.assertEqual(snapshot(self.dir_b), b_before)

    def test_path_traversal_is_rejected(self):
        path = self.backup_of(XUID_A)

        def escape(entries):
            manifest = json.loads(entries["manifest.json"])
            # Correct checksum, so only the path check can stop it
            manifest["files"]["../../evil.txt"] = {"size": 1, "sha256": hashlib.sha256(b"x").hexdigest()}
            entries["manifest.json"] = json.dumps(manifest).encode()
            entries["wgs/../../evil.txt"] = b"x"

        bad = self.tamper(path, escape)
        with self.assertRaisesRegex(GssError, "Unsafe path"):
            backup.read_backup(bad)
        a_before = snapshot(self.dir_a)
        self.assertEqual(self.run_gss("restore", bad, "-y", "-o", self.out), 1)
        self.assertEqual(snapshot(self.dir_a), a_before)

    def test_manifest_cant_point_restore_outside_packages(self):
        """The manifest's package and SCID name the folder a restore replaces."""
        path = self.backup_of(XUID_A)
        # A folder outside Packages that looks like a save folder, so only validation can protect it
        victim = self.tmp / "victim" / "SystemAppData" / "wgs" / user_dir_name(XUID_A, SCID)
        write_user_dir(victim, SAVE_B)
        victim_before = snapshot(victim)

        def point(**fields):
            def edit_manifest(entries):
                manifest = json.loads(entries["manifest.json"])
                manifest.update(fields)
                entries["manifest.json"] = json.dumps(manifest).encode()
            return edit_manifest

        cases = {
            "package": ["../victim", "..\\victim", "C:\\Windows", "", 5],
            "scid": ["../../x", "00000000000000000000000071672517\\..", "", "zz", 5],
            "xuid": [-1, 0, 2**64, "2535412345678901", True],
            "source_xuid": [-5, "x"],
            "files": [["wgs/x"], "x"],
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    bad = self.tamper(path, point(**{field: value}))
                    with self.assertRaises(GssError):
                        backup.read_backup(bad)
                    self.assertEqual(self.run_gss("restore", bad, "-y", "-o", self.out), 1)
                    bad.unlink()
        self.assertEqual(snapshot(victim), victim_before)
        self.assertEqual(saves(self.dir_a), SAVE_A)

    def test_other_bad_inputs(self):
        not_backup = self.tmp / "other.zip"
        with zipfile.ZipFile(not_backup, "w") as zf:
            zf.writestr("hello.txt", "hi")
        self.assertIn("not a gss backup", self.gss("restore", not_backup, "-y")[2])
        (self.tmp / "junk.zip").write_bytes(b"not a zip")
        self.assertIn("not a valid ZIP", self.gss("restore", self.tmp / "junk.zip", "-y")[2])
        self.assertIn("not found", self.gss("restore", self.tmp / "missing.zip", "-y")[2])

        path = self.backup_of(XUID_A)
        shutil.rmtree(self.root / PKG)
        self.assertIn("not installed", self.gss("restore", path, "-y", "-o", self.out)[2])
