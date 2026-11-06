import builtins
import shutil
from pathlib import Path

from gss import backup, edit, wgs
from gss.reset import build_reset_saves

from tests.fixtures import PKG, SAVE_A, SAVE_B, XUID_A, XUID_B, FakePackages, saves, snapshot, write_user_dir


class ResetTest(FakePackages):
    def reset(self, *args):
        return self.gss("reset", "--game", "dark ages", "--user", XUID_A, "-o", self.out, *args)

    def test_reset_deletes_every_save_and_marks_it_for_cloud_deletion(self):
        old = wgs.read_index(self.dir_a)
        b_before = snapshot(self.dir_b)

        code, out, _ = self.reset("-y")
        self.assertEqual(code, 0)
        self.assertIn("GAME-AUTOSAVE1: deleted, also from the cloud", out)
        self.assertIn("PROFILE: deleted, also from the cloud", out)

        # No saves left for the game to load
        self.assertEqual(saves(self.dir_a), {})
        new = wgs.read_index(self.dir_a)
        # Each save is a deletion marker with the account's cloud ETag, so Xbox deletes the cloud copy
        old_by_name = {c.name: c for c in old.containers}
        self.assertEqual([c.name for c in new.containers], ["GAME-AUTOSAVE1", "PROFILE"])
        for c in new.containers:
            self.assertEqual(c.state, wgs.SYNC_DELETED)
            self.assertEqual(c.etag, old_by_name[c.name].etag)
            self.assertTrue((self.dir_a / c.folder / c.file_name).is_file())
        # The account's sync identity is kept, and the index asks for an upload
        self.assertEqual(new.owner_id, old.owner_id)
        self.assertGreater(new.mtime, old.mtime)
        self.assertEqual(new.sync_flags, old.sync_flags & ~wgs.INDEX_FULLY_UPLOADED)
        # Other accounts aren't touched
        self.assertEqual(snapshot(self.dir_b), b_before)

    def test_never_uploaded_saves_are_just_removed(self):
        shutil.rmtree(self.dir_a)
        write_user_dir(self.dir_a, {**SAVE_A, "NEW-SLOT": {"x": b"local"}},
                       etags={"NEW-SLOT": ""}, states={"NEW-SLOT": wgs.SYNC_CREATED})
        code, out, _ = self.reset("-y")
        self.assertEqual(code, 0)
        self.assertIn("NEW-SLOT: deleted (it was never uploaded)", out)
        self.assertNotIn("NEW-SLOT", [c.name for c in wgs.read_index(self.dir_a).containers])

    def test_reset_only_some_saves(self):
        old = {c.name: c for c in wgs.read_index(self.dir_a).containers}
        code, out, _ = self.reset("--save", "GAME-AUTOSAVE1", "-y")
        self.assertEqual(code, 0)
        self.assertIn("PROFILE: kept as it is", out)
        self.assertEqual(saves(self.dir_a), {"PROFILE": SAVE_A["PROFILE"]})
        new = {c.name: c for c in wgs.read_index(self.dir_a).containers}
        self.assertEqual(new["GAME-AUTOSAVE1"].state, wgs.SYNC_DELETED)
        # The kept save is exactly as it was, so Xbox leaves it alone
        self.assertEqual(new["PROFILE"], old["PROFILE"])

    def test_unknown_save_name_changes_nothing(self):
        before = snapshot(self.dir_a)
        code, _, err = self.reset("--save", "NOPE", "-y")
        self.assertEqual(code, 1)
        self.assertIn("No save named NOPE", err)
        self.assertIn("GAME-AUTOSAVE1, PROFILE", err)
        self.assertEqual(snapshot(self.dir_a), before)

    def test_reset_twice_says_nothing_to_reset(self):
        self.assertEqual(self.reset("-y")[0], 0)
        code, _, err = self.reset("-y")
        self.assertEqual(code, 1)
        self.assertIn("no saves to reset", err)

    def test_undo_with_the_safety_backup(self):
        self.assertEqual(self.reset("-y")[0], 0)
        [safety] = [b for b in self.backups() if "before_reset" in b.name]
        self.assertEqual(backup.read_backup(safety).xuid, XUID_A)
        self.assertEqual(self.run_gss("restore", safety, "-y", "-o", self.out), 0)
        self.assertEqual(saves(self.dir_a), SAVE_A)
        # The deletion markers become changed saves again, still with the cloud's ETags
        for c in wgs.read_index(self.dir_a).containers:
            self.assertEqual(c.state, wgs.SYNC_MODIFIED)
            self.assertNotEqual(c.etag, "")

    def test_restore_into_a_reset_account(self):
        self.assertEqual(self.reset("-y")[0], 0)
        path = self.backup_of(XUID_B)
        self.assertEqual(self.run_gss("restore", path, "--to-xuid", XUID_A, "-y", "-o", self.out), 0)
        self.assertEqual(saves(self.dir_a), SAVE_B)

    def test_cancel_changes_nothing(self):
        before = snapshot(self.dir_a)
        original = builtins.input
        builtins.input = lambda *_: "n"
        try:
            code, _, err = self.reset()
        finally:
            builtins.input = original
        self.assertEqual(code, 1)
        self.assertIn("Cancelled", err)
        self.assertEqual(snapshot(self.dir_a), before)
        self.assertEqual(self.backups(), [])

    def test_game_and_user_must_pick_one_save(self):
        # Both are required
        for args in (["--game", "dark ages"], ["--user", str(XUID_A)]):
            with self.assertRaises(SystemExit):
                self.gss("reset", *args)
        # No match
        self.assertIn("No saves found", self.gss("reset", "--game", "nothing", "--user", XUID_A, "-y")[2])
        self.assertIn("No saves found", self.gss("reset", "--game", "dark", "--user", 2535400000000001, "-y")[2])
        # Ambiguous game
        self.add_game("SomePublisher.DarkThing_abcdefghijklm")
        code, _, err = self.gss("reset", "--game", "dark", "--user", XUID_A, "-y")
        self.assertEqual(code, 1)
        self.assertIn("more than one game", err)
        self.assertEqual(saves(self.dir_a), SAVE_A)
        # The game's ID picks one
        self.assertEqual(self.gss("reset", "--game", PKG, "--user", XUID_A, "-y", "-o", self.out)[0], 0)

    def test_half_synced_folder_is_refused(self):
        c = wgs.read_index(self.dir_a).containers[0]
        (self.dir_a / c.folder / c.file_name).unlink()
        before = snapshot(self.dir_a)
        code, _, err = self.reset("-y")
        self.assertEqual(code, 1)
        self.assertIn("still syncing", err)
        self.assertEqual(snapshot(self.dir_a), before)

    def test_failure_puts_saves_back(self):
        before = snapshot(self.dir_a)
        original = edit.shutil.copytree

        def broken_copytree(src, dst, *a, **kw):
            Path(dst).mkdir(parents=True)
            raise OSError("disk full")

        edit.shutil.copytree = broken_copytree
        try:
            code, _, err = self.reset("-y")
        finally:
            edit.shutil.copytree = original
        self.assertEqual(code, 1)
        self.assertIn("previous saves were put back", err)
        self.assertEqual(snapshot(self.dir_a), before)

    def test_extract_after_reset_finds_nothing(self):
        self.assertEqual(self.reset("-y")[0], 0)
        code, out, _ = self.gss("extract", "--user", XUID_A, "-o", self.tmp / "extracted")
        self.assertIn("No save files", out)

    def test_build_reset_saves_directly(self):
        out = self.tmp / "out"
        changes = build_reset_saves(self.dir_a, out)
        self.assertEqual([(c.save, c.action) for c in changes], [("GAME-AUTOSAVE1", "delete"), ("PROFILE", "delete")])
        self.assertEqual(saves(out), {})
        self.assertEqual(saves(self.dir_a), SAVE_A)  # the account's folder isn't touched
