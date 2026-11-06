import shutil

from gss import status, wgs

from tests.fixtures import SAVE_A, XUID_A, XUID_B, FakePackages, write_user_dir


class StatusTest(FakePackages):
    def status_of(self, xuid=XUID_A):
        return self.gss("status", "--game", "dark ages", "--user", xuid)

    def rewrite(self, **kwargs):
        shutil.rmtree(self.dir_a)
        write_user_dir(self.dir_a, kwargs.pop("containers", SAVE_A), **kwargs)

    def test_synced(self):
        code, out, _ = self.status_of()
        self.assertEqual(code, 0)
        self.assertIn(f"DOOM: The Dark Ages - account {XUID_A}", out)
        self.assertRegex(out, r"GAME-AUTOSAVE1\s+synced\s+5 KB\s+\d{4}-\d\d-\d\d \d\d:\d\d")
        self.assertRegex(out, r"PROFILE\s+synced\s+9 B")
        self.assertIn("OK: Everything is synced", out)
        self.assertEqual(status.save_status(self.dir_a).slot_names, ["GAME-AUTOSAVE1", "PROFILE"])

    def test_after_copy_saves_wait_for_upload(self):
        self.assertEqual(self.run_gss("copy", "--game", "dark", "--from", XUID_A, "--to", XUID_B, "-y", "-o", self.out), 0)
        code, out, _ = self.status_of(XUID_B)
        self.assertEqual(code, 2)
        self.assertRegex(out, r"GAME-AUTOSAVE1\s+changed, waiting for upload")
        self.assertIn("Waiting: Not everything is uploaded yet", out)

    def test_after_reset_saves_wait_for_cloud_deletion(self):
        self.assertEqual(self.run_gss("reset", "--game", "dark", "--user", XUID_A, "--save", "PROFILE", "-y", "-o", self.out), 0)
        code, out, _ = self.status_of()
        self.assertEqual(code, 2)
        self.assertRegex(out, r"PROFILE\s+deleted, waiting to be deleted in the cloud")
        self.assertRegex(out, r"GAME-AUTOSAVE1\s+synced")
        # Deleted slots aren't offered as names for reset --save
        self.assertEqual(status.save_status(self.dir_a).slot_names, ["GAME-AUTOSAVE1"])

    def test_every_sync_state_is_described(self):
        self.rewrite(containers={"A": {"x": b"1"}, "B": {"x": b"1"}, "C": {"x": b"1"}, "D": {"x": b"1"}},
                     states={"A": 0, "B": wgs.SYNC_CREATED, "C": 4, "D": wgs.SYNC_SYNCED})
        out = self.status_of()[1]
        self.assertRegex(out, r"A\s+on this PC only")
        self.assertRegex(out, r"B\s+new, waiting for upload")
        self.assertRegex(out, r"C\s+unknown sync state 4")
        self.assertRegex(out, r"D\s+synced")

    def test_a_waiting_save_counts_even_if_the_index_says_uploaded(self):
        self.rewrite(states={"PROFILE": wgs.SYNC_MODIFIED}, sync_flags=3)
        code, out, _ = self.status_of()
        self.assertEqual(code, 2)
        self.assertIn("Waiting: Not everything is uploaded yet", out)

    def test_index_flags(self):
        # Saves all synced, but the index says not everything is uploaded
        self.rewrite(sync_flags=2)
        self.assertEqual(status.save_status(self.dir_a).summary, status.PENDING)
        self.assertIn("uploaded", status.save_status(self.dir_a).message)
        # ... or downloaded
        self.rewrite(sync_flags=1)
        self.assertEqual(status.save_status(self.dir_a).summary, status.PENDING)
        self.assertIn("downloaded", status.save_status(self.dir_a).message)
        # Conflict flag
        self.rewrite(sync_flags=3 | 16)
        code, out, _ = self.status_of()
        self.assertEqual(code, 3)
        self.assertIn("!! Xbox may have found a sync conflict", out)

    def test_half_synced_folder(self):
        c = wgs.read_index(self.dir_a).containers[0]
        (self.dir_a / c.folder / c.file_name).unlink()
        code, out, _ = self.status_of()
        self.assertEqual(code, 3)
        self.assertIn("!! Incomplete: the saves can't be read", out)
        self.assertNotIn("SAVE SLOT", out)

    def test_missing_save_data(self):
        c = wgs.read_index(self.dir_a).containers[1]
        (self.dir_a / c.folder / c.blobs[0].current_atom.hex.upper()).unlink()
        code, out, _ = self.status_of()
        self.assertEqual(code, 3)
        self.assertRegex(out, r"PROFILE\s+data missing")
        self.assertRegex(out, r"GAME-AUTOSAVE1\s+synced")
        self.assertIn("!! Incomplete: some save data is missing", out)

    def test_several_accounts_report_the_worst(self):
        self.assertEqual(self.gss("status")[0], 0)
        # The problem is on account B, which is listed after A
        shutil.rmtree(self.dir_b)
        write_user_dir(self.dir_b, SAVE_A, sync_flags=2)
        code, out, _ = self.gss("status")
        self.assertEqual(code, 2)
        self.assertIn(str(XUID_A), out)
        self.assertIn(str(XUID_B), out)

    def test_filters_and_no_saves(self):
        out = self.gss("status", "--user", XUID_B)[1]
        self.assertNotIn(str(XUID_A), out)
        code, out, _ = self.gss("status", "--game", "nothing like this")
        self.assertEqual(code, 1)
        self.assertIn("No saves found matching the filters", out)

    def test_sizes(self):
        from gss.cli import format_size
        self.assertEqual([format_size(n) for n in (0, 1023, 1024, 191532, 5 * 1024 * 1024)],
                         ["0 B", "1023 B", "1 KB", "187 KB", "5.0 MB"])
