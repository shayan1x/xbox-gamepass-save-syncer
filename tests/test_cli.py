import shutil

from gss import cli, games

from tests.fixtures import PKG, XUID_A, XUID_B, FakePackages

OTHER = "SomePublisher.UnknownGame_abcdefghijklm"


class ListTest(FakePackages):
    def list_output(self, *args) -> str:
        code, out, _ = self.gss("list", "--backups", self.out, *args)
        self.assertEqual(code, 0)
        return out

    def test_games_ids_and_accounts(self):
        self.add_game(OTHER)
        (self.root / "NoSaves.App_123").mkdir()
        out = self.list_output()
        for text in ["DOOM: The Dark Ages", PKG, OTHER, "SomePublisher.UnknownGame ",
                     str(XUID_A), str(XUID_B), "000901F1B0392C35", "00090205CF3DF52D"]:
            self.assertIn(text, out)
        self.assertNotIn("NoSaves", out)
        game_rows = out.split("Xbox accounts")[0]
        # Every row is complete, even for a second account of the same game
        self.assertRegex(game_rows, rf"DOOM: The Dark Ages\s+{PKG}\s+{XUID_A}\s")
        self.assertRegex(game_rows, rf"DOOM: The Dark Ages\s+{PKG}\s+{XUID_B}\s")
        accounts = out.split("Xbox accounts")[1].split("Backups")[0]
        self.assertRegex(accounts, rf"{XUID_A}\s+000901F1B0392C35\s+\S+\s+2")
        self.assertRegex(accounts, rf"{XUID_B}\s+00090205CF3DF52D\s+\S+\s+1")
        self.assertIn("None", out.split("Backups")[1])

    def test_ids_from_list_work_with_backup(self):
        self.add_game(OTHER)
        self.assertEqual(self.run_gss("backup", "--game", OTHER, "--user", "000901F1B0392C35", "-o", self.out), 0)
        [path] = self.backups()
        from gss.backup import read_backup
        self.assertEqual(read_backup(path).package, OTHER)

    def test_filters(self):
        game_rows = self.list_output("--user", XUID_B).split("Xbox accounts")[0]
        self.assertIn(str(XUID_B), game_rows)
        self.assertNotIn(str(XUID_A), game_rows)
        self.assertIn("No saves found matching the filters", self.list_output("--game", "nothing like this"))

    def test_backups_and_invalid_ones(self):
        self.assertEqual(self.run_gss("backup", "--user", XUID_A, "--to-xuid", XUID_B, "-o", self.out), 0)
        backup_b = self.backup_of(XUID_B)
        (self.out / "broken.zip").write_bytes(b"not a zip")

        backups = self.list_output().split("Backups in")[1]
        self.assertIn(backup_b.name, backups)
        self.assertIn(f"{XUID_B} (from {XUID_A})", backups)
        self.assertRegex(backups, r"broken\.zip.*INVALID")
        self.assertEqual(backups.count(" OK"), 2)

        from_a = self.list_output("--user", XUID_A).split("Backups in")[1]
        self.assertNotIn(backup_b.name, from_a)
        self.assertIn(f"(from {XUID_A})", from_a)

    def test_no_saves_at_all(self):
        shutil.rmtree(self.root / PKG)
        out = self.list_output()
        self.assertIn("No saves found", out)
        self.assertNotIn("Xbox accounts", out)

    def test_windows_names_for_games_not_in_games_json(self):
        self.add_game(OTHER)
        asked = []

        def fake_names(packages):
            asked.append(set(packages))
            return {OTHER: "The Unknown Game"}

        original = games.installed_display_names
        import gss.discovery
        gss.discovery.installed_display_names = fake_names
        try:
            self.assertIn("The Unknown Game", self.list_output())
            self.assertEqual(asked[0], {OTHER})  # only games missing from games.json are looked up
            self.assertEqual(self.run_gss("backup", "--game", "unknown game", "-o", self.out), 0)
        finally:
            gss.discovery.installed_display_names = original
        [path] = self.backups()
        self.assertTrue(path.name.startswith("the_unknown_game_"))

    def test_display_name_lookup_ignores_unsafe_package_names(self):
        calls = []
        original = games.subprocess.run

        def fake_run(*a, **kw):
            calls.append(a)
            raise OSError("no powershell here")

        games.subprocess.run = fake_run
        try:
            self.assertEqual(games.installed_display_names({"x'; Remove-Item C:\\ -Recurse; '_abcdefghijklm"}), {})
            self.assertEqual(calls, [])
            self.assertEqual(games.installed_display_names({PKG}), {})
        finally:
            games.subprocess.run = original
        if games.shutil.which("powershell") or games.shutil.which("pwsh"):
            self.assertEqual(len(calls), 1)


class CliTest(FakePackages):
    def no_arguments(self, double_click: bool):
        import builtins
        asked = []
        original_input, original_check = builtins.input, cli.opened_by_double_click
        builtins.input = lambda prompt="": asked.append(prompt) or ""
        cli.opened_by_double_click = lambda: double_click
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        try:
            with redirect_stdout(out):
                code = cli.main([])
        finally:
            builtins.input, cli.opened_by_double_click = original_input, original_check
        return code, out.getvalue(), asked

    def test_no_arguments_shows_a_guide(self):
        code, out, asked = self.no_arguments(double_click=False)
        self.assertEqual(code, 0)
        self.assertIn("This is a command-line tool", out)
        self.assertIn("copy --game", out)
        self.assertIn("usage:", out)
        self.assertEqual(asked, [])  # run from Command Prompt: don't wait

    def test_double_click_waits_before_closing(self):
        code, out, asked = self.no_arguments(double_click=True)
        self.assertEqual(code, 0)
        self.assertEqual(len(asked), 1)
        self.assertIn("Press Enter", asked[0])

    def test_double_click_detection_from_a_terminal(self):
        # The tests run in a shared console, never one opened just for them
        self.assertFalse(cli.opened_by_double_click())

    def test_program_name(self):
        import sys
        original_argv, original_frozen = sys.argv, getattr(sys, "frozen", None)
        try:
            sys.argv = ["C:\\gss\\gss.py"]
            self.assertEqual(cli.program_name(), "python gss.py")
            sys.argv = ["C:\\venv\\Scripts\\gss.exe"]
            self.assertEqual(cli.program_name(), "gss")
            sys.argv, sys.frozen = ["gss.py"], True
            self.assertEqual(cli.program_name(), "gss")
        finally:
            sys.argv = original_argv
            if original_frozen is None:
                del sys.frozen
            else:
                sys.frozen = original_frozen

    def test_version_is_always_gss(self):
        from gss import __version__
        with self.assertRaises(SystemExit):
            self.gss("--version")
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit):
            cli.main(["--version"])
        self.assertEqual(out.getvalue().strip(), f"gss {__version__}")

    def test_bad_xuid_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as e:
            self.gss("backup", "--user", "not-a-xuid")
        self.assertEqual(e.exception.code, 2)

    def test_version_and_help(self):
        for args in (["--version"], ["--help"], ["restore", "--help"]):
            with self.assertRaises(SystemExit) as e:
                self.gss(*args)
            self.assertEqual(e.exception.code, 0)

    def test_unprintable_game_names_dont_crash(self):
        import io
        import sys
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        original = sys.stdout
        sys.stdout = stream
        try:
            cli.main(["--packages-root", str(self.root), "list", "--backups", str(self.out)])
            print("ドラゴンクエスト™")
        finally:
            sys.stdout = original

    def test_packages_root_from_environment(self):
        import os
        from gss.discovery import PACKAGES_ROOT_ENV, default_packages_root
        from contextlib import redirect_stdout
        import io
        os.environ[PACKAGES_ROOT_ENV] = str(self.root)
        try:
            self.assertEqual(default_packages_root(), self.root)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["backup", "--user", str(XUID_A), "-o", str(self.out)]), 0)
        finally:
            del os.environ[PACKAGES_ROOT_ENV]
        self.assertEqual(len(self.backups()), 1)
