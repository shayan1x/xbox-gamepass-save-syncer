# Contributing to gamepass-save-syncer

Thanks for helping! gss handles people's game saves, often hundreds of hours of progress, so this guide puts **safety first**. Most of it is about keeping that true.

Using an AI coding agent? Point it at [AGENTS.md](AGENTS.md), which has the same rules plus the commands, checks and known pitfalls an agent needs.

There are many ways to help, and most don't need any code:

- [Report a tested game](#report-a-tested-game): the most useful contribution right now
- [Report a bug](#report-a-bug)
- [Add a game for `extract`](#add-a-game-for-extract)
- [Change the code](#change-the-code)

---

## Report a tested game

Copy works for any Game Pass game in principle, but the README's [tested games](README.md#tested-games) table lists only games someone has checked end to end. To add one, open an issue or a pull request with:

- **The game's name and ID**, from `gss list`.
- **What you tried:** `copy`, `restore`, `reset` or `backup`.
- **The result**, checked the full way through:
  1. The command finished without errors.
  2. The game loaded the copied or restored progress on the target account.
  3. After you quit the game, `gss status` showed every slot as **synced**.
- **Anything unusual**, for example a sync-conflict prompt from Xbox and which choice you made.

A game that **didn't** work is just as useful to report. Please include the `gss status` output from before and after.

---

## Report a bug

Open an issue with:

1. **What you ran**: the full command.
2. **What happened**: the full output, including any `Error:` line.
3. **What you expected** instead.
4. **`gss status --game "<game>"`** output, which shows the sync state of each save slot.
5. Your Windows version, Python version (`python --version`) and gss version (`python gss.py --version`).

> [!IMPORTANT]
> **Remove your account IDs before posting.** `gss list`, `gss status` and file paths show your Xbox account IDs (XUIDs). Replace them with made-up ones such as `2535412345678901`, and your Windows user name with `you`. Never attach save files or backup ZIPs to a public issue, because they contain your progress and account IDs.

If a command damaged a save, say so in the title. Every command that changes saves keeps a `..._before_*.zip` backup, so mention whether restoring it brought the save back.

---

## Add a game for `extract`

`extract` converts saves for the Steam/Epic version of a game, using rules in [`src/gss/games.json`](src/gss/games.json). Each game has an Xbox package ID and a **handler**, which says how its save files map to Steam/Epic files:

```json
{
    "name": "DOOM: The Dark Ages",
    "package": "BethesdaSoftworks.ProjectTitan_3275kfvn8vcwc",
    "handler": "1cnf-folder"
}
```

1. **Find the package ID** with `gss list` (the **ID** column).
2. **Look at the save layout:** `gss status --game "<game>"` lists the save slots. Then compare with the Steam/Epic save folder on [PCGamingWiki](https://www.pcgamingwiki.com/).
3. **Pick a handler.** Each one is documented in [`src/gss/extract.py`](src/gss/extract.py). The common ones are:

   | Handler | Xbox layout | Steam/Epic result |
   |---|---|---|
   | `1c1f` | One file per save slot | One file per slot, named after the slot (optional `suffix`, e.g. `.sav`) |
   | `1cnf` | One slot holding all the files | The files as they are (optional `suffix`) |
   | `1cnf-folder` | Each slot is a folder of files | `<slot>/<file>` |

4. **Add the entry to its handler's group.** The file is grouped by handler, and each group starts with a `//` comment. Games that need their own handler get their own `//` comment.
5. **Test it:** run `gss extract --game "<game>"`, copy the result into the Steam/Epic save folder, and check that the game loads it. Say in the pull request which store you tested with.

If no handler fits, a new one is a small function in `extract.py` registered with `@handler("<name>")`. It needs a test in [`tests/test_extract.py`](tests/test_extract.py).

The game list started as [XGP-save-extractor](https://github.com/Z1ni/XGP-save-extractor)'s. Games added there can usually be added here the same way.

---

## Change the code

### Setup

You need Windows 10 or 11 and **Python 3.10 or newer**. There are no dependencies to install.

```bash
git clone https://github.com/shayan1x/xbox-gamepass-save-syncer.git
```
```bash
cd xbox-gamepass-save-syncer
```
```bash
python -m unittest
```

Run the tool straight from the folder with `python gss.py <command>`. Alternatively, run `pip install -e .` to get a `gss` command that uses your working copy.

The tests build fake save folders in a temp directory. They **never touch real saves**, and they don't need an Xbox account, Game Pass or any installed games.

### Project structure

```
gss.py                  Runs gss from the folder without installing it
src/gss/
  cli.py                The gss command: argument parsing and all printing and prompting
  wgs.py                The Xbox save format (containers.index, container.N): read and write
  discovery.py          Finds save folders under %LOCALAPPDATA%\Packages
  accounts.py           XUIDs and the save folder names built from them
  games.py              games.json and game display names from Windows
  backup.py             Backup ZIPs: write, check, read, unpack
  restore.py            restore and copy
  reset.py              reset
  edit.py               The steps restore, copy and reset share to change saves safely
  status.py             Sync status of an account's saves
  extract.py            Steam/Epic conversion handlers
  games.json            Games extract can convert
tests/
  fixtures.py           Writes fake save folders byte by byte, independent of wgs.py
  test_*.py             One file per area
```

### How changing saves works

Read the docstrings at the top of [`wgs.py`](src/gss/wgs.py), [`restore.py`](src/gss/restore.py) and [`edit.py`](src/gss/edit.py) before changing anything that writes saves. In short:

- Each save slot in `containers.index` records the **cloud version (ETag)** it was last synced at, and a **sync state**.
- If gss writes files that look older than the cloud copy, Xbox downloads the cloud copy over them **without asking**. That's why copying files by hand fails.
- So every change goes through the same steps in `edit.py`:
  1. Read the target account's **own** index, and refuse if it's half-synced.
  2. Build the new saves in a temp folder, keeping the target's ETags and marking changes as *modified*, *created* or *deleted*.
  3. Back up the current saves (`..._before_*.zip`).
  4. Swap the new folder in, check it, and **roll back** if anything fails.

### Rules for code changes

These keep users' saves safe. A pull request that breaks one needs a very good reason.

1. **Never write to a save folder outside `edit.swap_in()`.** That's where the safety backup and rollback live.
2. **Never copy ETags from a backup or another account.** Always keep the target account's own, as `restore.build_restored_saves()` does.
3. **Refuse rather than guess.** If a folder is half-synced, a name is ambiguous, or the data looks wrong, stop with a clear `GssError` that says what to do.
4. **The library doesn't print or prompt.** Only `cli.py` talks to the user. Library functions take a `confirm` callback where a question is needed.
5. **Errors users will see are `GssError`s**, written as plain sentences that say what to do next. Tracebacks are for bugs.
6. **Python standard library only.** No dependencies, so the tool keeps running from a downloaded ZIP and `gss.exe` stays small. PyInstaller is only needed to build `gss.exe`.
7. **Python 3.10 compatible.** Don't use newer syntax or library features.

### Tests

- **Every change needs tests.** For anything that writes saves, test at least:
  - the happy path
  - a refusal, such as a half-synced folder, a wrong argument or a cancel
  - rollback on failure
- **Use the fixtures.** `FakePackages` in [`tests/fixtures.py`](tests/fixtures.py) gives you a fake `Packages` folder with two accounts. `write_user_dir()` can set sync states, ETags and index flags.
- **Check that the test fails without your change.** Temporarily break the line your test is about and make sure a test fails. Several gaps in the test suite were found this way.
- **Never use real saves or real XUIDs in tests.** The fixtures use made-up IDs.

### Checking against real saves

Before a change that writes saves is merged, it should also work on real data. Do that on a **copy** of your saves, never on the real folder:

1. Copy a game's `%LOCALAPPDATA%\Packages\<package>\SystemAppData\wgs` folder to a temp folder, keeping the same structure under a `Packages` folder.
2. Point gss at the copy with the `--packages-root` option, which is hidden from `--help` and meant for testing:

   ```bash
   python gss.py --packages-root C:\temp\copy\Packages status
   ```

The final test is the game itself. Run the command for real (it makes a safety backup), start the game, check the progress, quit, and confirm with `gss status` that everything is **synced**. Mention in the pull request which games you checked this way.

### Style

- Follow the code around you: type hints on functions, and a docstring wherever the *why* isn't obvious.
- Keep lines under about 120 characters.
- Write user-facing messages in plain language, for people who aren't developers.
- Update the [README](README.md) when commands, options or behaviour change. It's written for non-technical users.

### Commits and pull requests

- **One topic per pull request**, with tests and README changes included.
- **Commit messages:** a short summary line in the imperative mood ("Add copy command…", "Fix …"), then a blank line and a body that says *what* changed and *why*. Look at `git log` for examples.
- **Describe in the pull request:** what changed, how you tested it (unit tests, a sandbox copy, in-game), and anything you're unsure about.
- `python -m unittest` must pass.

---

## Releases

gss follows [Semantic Versioning](https://semver.org/):

| Change | Version bump |
|---|---|
| Fixes only | patch: `0.1.0` → `0.1.1` |
| New commands, options or games | minor: `0.1.0` → `0.2.0` |
| README or other docs only | no new version |

To release:
1. Set the version in **both** [`pyproject.toml`](pyproject.toml) and [`src/gss/__init__.py`](src/gss/__init__.py).
2. Commit, then tag the commit `vX.Y.Z` and push both.
3. Create a GitHub release from the tag, with notes on what changed for users.
4. Publishing the release starts the [Build gss.exe](.github/workflows/release.yml) workflow. It:
   - runs the tests
   - builds `gss.exe`
   - checks it with [`packaging/smoke_test.py`](packaging/smoke_test.py), including that its version matches the tag
   - attaches `gss.exe` and `gss.exe.sha256` to the release

   Check the **Actions** tab if they don't appear after a few minutes.

To build `gss.exe` yourself:

```bash
python -m pip install pyinstaller==6.11.1
```
```bash
python -m PyInstaller packaging/gss.spec
```
```bash
python packaging/smoke_test.py dist/gss.exe
```

The build settings are in [`packaging/gss.spec`](packaging/gss.spec). It starts from `packaging/gss_exe.py`, not `gss.py`, because a script named `gss.py` would hide the `gss` package inside the `.exe`.

Never move or re-create a tag that has been pushed: people who downloaded that version should be able to get the same files again.

---

## License

By contributing, you agree that your contributions are licensed under the project's [MIT License](LICENSE). Code derived from [XGP-save-extractor](https://github.com/Z1ni/XGP-save-extractor) keeps its original copyright notice. Please keep that attribution when you change `extract.py` or `games.json`.
