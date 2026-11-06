import builtins

from gss import wgs
from gss.accounts import user_dir_name

from tests.fixtures import PKG, SAVE_A, SAVE_B, SCID, XUID_A, XUID_B, FakePackages, saves, snapshot


class CopyTest(FakePackages):
    def copy(self, *args, src=XUID_A, dst=XUID_B):
        return self.gss("copy", "--game", "dark ages", "--from", src, "--to", dst, "-o", self.out, *args)

    def test_copy_moves_saves_and_keeps_target_cloud_state(self):
        a_before = snapshot(self.dir_a)
        b_old = wgs.read_index(self.dir_b)

        code, out, _ = self.copy("-y")
        self.assertEqual(code, 0)
        self.assertIn(f"From:        {XUID_A}", out)
        self.assertIn(f"To:          {XUID_B}", out)
        self.assertIn("GAME-AUTOSAVE1: replaced, uploaded to the cloud", out)

        self.assertEqual(saves(self.dir_b), SAVE_A)
        self.assertEqual(snapshot(self.dir_a), a_before)  # the source isn't touched
        # Same cloud-safe result as backup + restore: B's ETags and identity, marked for upload
        new = wgs.read_index(self.dir_b)
        self.assertEqual(new.owner_id, b_old.owner_id)
        self.assertEqual([(c.etag, c.state) for c in new.containers],
                         [(c.etag, wgs.SYNC_MODIFIED) for c in b_old.containers])

    def test_only_the_target_safety_backup_is_kept(self):
        self.assertEqual(self.copy("-y")[0], 0)
        [safety] = self.backups()
        self.assertIn(f"{XUID_B}_before_restore", safety.name)
        # It undoes the copy
        self.assertEqual(self.run_gss("restore", safety, "-y", "-o", self.out), 0)
        self.assertEqual(saves(self.dir_b), SAVE_B)

    def test_copy_back_and_forth(self):
        self.assertEqual(self.copy("-y")[0], 0)
        self.assertEqual(self.copy("-y", src=XUID_B, dst=XUID_A)[0], 0)
        self.assertEqual(saves(self.dir_a), SAVE_A)
        self.assertEqual(saves(self.dir_b), SAVE_A)

    def test_xuids_in_hex(self):
        code, _, _ = self.gss("copy", "--game", PKG, "--from", "000901F1B0392C35", "--to", "0x00090205CF3DF52D",
                              "-y", "-o", self.out)
        self.assertEqual(code, 0)
        self.assertEqual(saves(self.dir_b), SAVE_A)

    def test_same_account_is_refused(self):
        before = snapshot(self.dir_a)
        code, _, err = self.copy("-y", dst=XUID_A)
        self.assertEqual(code, 1)
        self.assertIn("same Xbox account", err)
        self.assertEqual(snapshot(self.dir_a), before)

    def test_target_without_saves_is_refused(self):
        code, _, err = self.copy("-y", dst=2535400000000001)
        self.assertEqual(code, 1)
        self.assertIn("start the game once", err)
        self.assertFalse((self.wgs / user_dir_name(2535400000000001, SCID)).exists())
        self.assertEqual(self.backups(), [])

    def test_source_without_saves_or_ambiguous_game(self):
        self.assertIn("No saves found", self.copy("-y", src=2535400000000001)[2])
        self.add_game("SomePublisher.DarkThing_abcdefghijklm")
        code, _, err = self.gss("copy", "--game", "dark", "--from", XUID_A, "--to", XUID_B, "-y", "-o", self.out)
        self.assertEqual(code, 1)
        self.assertIn("more than one game", err)
        self.assertEqual(saves(self.dir_b), SAVE_B)

    def test_arguments_are_required(self):
        for args in (["--game", "x", "--from", str(XUID_A)], ["--game", "x", "--to", str(XUID_B)],
                     ["--from", str(XUID_A), "--to", str(XUID_B)]):
            with self.assertRaises(SystemExit):
                self.gss("copy", *args)

    def test_cancel_changes_nothing(self):
        b_before = snapshot(self.dir_b)
        original = builtins.input
        builtins.input = lambda *_: "n"
        try:
            code, _, err = self.copy()
        finally:
            builtins.input = original
        self.assertEqual(code, 1)
        self.assertIn("Cancelled", err)
        self.assertEqual(snapshot(self.dir_b), b_before)
        self.assertEqual(self.backups(), [])

    def test_half_synced_source_is_refused(self):
        c = wgs.read_index(self.dir_a).containers[0]
        (self.dir_a / c.folder / c.file_name).unlink()
        b_before = snapshot(self.dir_b)
        code, _, err = self.copy("-y")
        self.assertEqual(code, 1)
        self.assertIn("incomplete", err)
        self.assertEqual(snapshot(self.dir_b), b_before)
