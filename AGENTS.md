# AGENTS.md

Instructions for AI coding agents working on **gamepass-save-syncer (gss)**. Human contributors: see [CONTRIBUTING.md](CONTRIBUTING.md), which this file builds on rather than repeats.

> [!IMPORTANT]
> gss rewrites people's game saves, often hundreds of hours of progress. **A wrong change can silently destroy a save, or let Xbox cloud sync overwrite one.** Read [Safety rules](#safety-rules) before changing anything under `src/gss/`, and never run a save-changing command against the user's real saves.

## Project in one paragraph

gss is a Windows command-line tool, written in Python 3.10+ with only the standard library. It copies Xbox Game Pass for PC saves between Xbox accounts, and also lists, backs up, restores, resets and checks the sync status of saves, and converts them for Steam/Epic. Saves live in `%LOCALAPPDATA%\Packages\<package>\SystemAppData\wgs\<XUID hex>_<SCID>\`. The hard part, and the reason gss exists, is that **files copied by hand get overwritten by Xbox cloud sync**. gss rewrites the account's `containers.index` so Xbox **uploads** the change instead. It ships as source code and as a standalone `gss.exe` built by GitHub Actions.

## Commands

All commands run from the repository root, on Windows.

| Task | Command |
|---|---|
| Run the tests (must pass before every commit) | `python -m unittest` |
| Run the tests on the oldest supported Python | `py -3.10 -m unittest` |
| Run gss from source | `python gss.py <command>` (e.g. `python gss.py list`) |
| Run gss against a sandbox instead of the real saves | `python gss.py --packages-root <dir>\Packages <command>` |
| Build gss.exe | `python -m pip install pyinstaller==6.11.1` then `python -m PyInstaller packaging/gss.spec` |
| Check a built gss.exe | `python packaging/smoke_test.py dist/gss.exe [vX.Y.Z]` |

- **No dependencies:** there's nothing to install for development. PyInstaller is only needed to build the `.exe`.
- **Clean up afterwards:** delete `__pycache__` folders and any `build/`, `dist/` or `*.egg-info` you create. Also leave the user's `backups/` and `extracted/` folders alone. They're gitignored and may hold their real backups.

## Project map

```
gss.py                      Run from source: adds src/ to sys.path, calls gss.cli.main
src/gss/
  __init__.py               __version__ and GssError
  cli.py                    argparse, ALL printing and prompting, exit codes
  wgs.py                    Xbox save format: read/write containers.index and container.N, read_saves()
  edit.py                   Shared save-changing steps: read_current, delete_container, write_index, swap_in
  restore.py                restore_backup, copy_saves, build_restored_saves
  reset.py                  reset_saves, build_reset_saves
  status.py                 save_status: sync state per slot, summary SYNCED/PENDING/CONFLICT/INCOMPLETE
  backup.py                 Backup ZIPs: create_backup, read_backup (validation), extract_backup
  discovery.py              find_saves, discover; packages root (GSS_PACKAGES_ROOT env var for testing)
  accounts.py               parse_xuid, user_dir_name, split_user_dir_name, gamertag
  games.py                  games.json catalog, Windows display names (PowerShell), game_matches
  extract.py                Steam/Epic conversion handlers, registered with @handler("<name>")
  fsutil.py                 sha256_file, safe_relpath, remove_tree, slugify, unique_path
  games.json                Games extract can convert (JSON with // comment lines, grouped by handler)
tests/
  fixtures.py               FakePackages test case and write_user_dir(): fake saves written byte by byte
  test_*.py                 One file per area: wgs, backup_restore, copy, reset, status, extract, cli
packaging/
  gss.spec                  PyInstaller one-file build (entry: gss_exe.py, NOT gss.py)
  gss_exe.py                Entry point of gss.exe
  smoke_test.py             Runs a built gss.exe on fake saves from a folder outside the project
.github/workflows/
  release.yml               On a published release: tests, build, smoke test, attach gss.exe + .sha256
```

## How saves change safely

Read the module docstrings of [`wgs.py`](src/gss/wgs.py), [`restore.py`](src/gss/restore.py) and [`edit.py`](src/gss/edit.py) before touching anything that writes saves. The essentials:

- **`containers.index`** lists each save slot ("container") with its cloud **ETag**, a **sync state** (1 synced, 2 modified, 3 deleted, 5 created) and a container GUID. The index header has sync flags (1 = fully uploaded) and an `ownerChangedID`.
- **`container.N`** lists the slot's files ("blobs"). Each blob has a **last synced atom** (the cloud's ID for it) and a **current atom** (the local data file).
- **If the index claims a save is synced but its ETag differs from the cloud's, Xbox downloads the cloud copy over it.** That's what happens when files are copied by hand.
- **So every change follows the same recipe:**
  1. Read the **target account's own** index, with `edit.read_current()`.
  2. Build the new saves in a temp folder. Keep the target's ETags, `ownerChangedID` and last synced atoms. Give changed data new current atoms. Mark slots *modified* (or *created* if the cloud doesn't have them). Mark removed slots *deleted*, rather than dropping them.
  3. Write an index that's newer than the old one and has the fully-uploaded flag cleared, with `edit.write_index()`.
  4. Swap the result in with `edit.swap_in()`, which backs up first (`..._before_*.zip`), checks the result, and rolls back on any failure.

This recipe was confirmed on real saves and in-game: a restored save survived the next sync and was uploaded with new ETags.

## Safety rules

These are hard rules. Breaking one needs an explicit go-ahead from the maintainer.

1. **Write to save folders only through `edit.swap_in()`.** No other code may delete or replace a `wgs\<user>` folder.
2. **Never copy ETags, `ownerChangedID` or last synced atoms from a backup or another account.** They must come from the target account's current index.
3. **Validate everything that names a path.** Backup manifests (`package`, `scid`, XUIDs, file paths) are untrusted input, and `backup.read_backup()` must reject anything that could point outside the save folder. A crafted manifest was once able to make restore replace a folder outside `Packages` (fixed in v0.1.1).
4. **Refuse rather than guess.** For a half-synced folder, an ambiguous `--game`, a missing target account folder or unexpected data, raise a `GssError` that tells the user what to do.
5. **The library never prints or prompts.** Only `cli.py` does. Library functions take a `confirm` callback.
6. **Standard library only, Python 3.10 compatible.** No new dependencies, and no syntax or APIs newer than 3.10.
7. **PowerShell is the only external program**, used in `games.installed_display_names()`. Its input must pass `PACKAGE_FAMILY_RE`. Add no other subprocesses, and no network access.

## Never touch the user's real saves

- **Allowed on real saves:** `list`, `status`, and `backup` or `extract` **into a temp folder** (`-o <temp dir>`). These only read saves.
- **Never on real saves:** `copy`, `restore` and `reset`, which change saves. Use a sandbox instead:
  1. Copy `%LOCALAPPDATA%\Packages\<package>\SystemAppData\wgs` to `<temp>\Packages\<package>\SystemAppData\wgs`.
  2. Run gss with `--packages-root <temp>\Packages`.
  3. Before and after, take a SHA-256 snapshot of every file under the real `wgs` folders, and confirm nothing changed.
- **Only the user tests in-game.** If a change needs in-game testing, say so and leave it to them.
- **Unit tests use fixtures only.** `tests/fixtures.py` builds fake `Packages` folders in a temp directory.

## Testing expectations

- **Every behaviour change needs tests**, in the matching `tests/test_*.py`. For anything that writes saves, cover:
  - the happy path
  - a refusal, such as a half-synced folder, a bad argument or a cancel
  - rollback on failure (patch `edit.shutil.copytree` to raise)
- **Use `FakePackages`.** It gives `self.root`, `self.dir_a`, `self.dir_b`, `self.out`, `self.gss(*args)` returning `(code, stdout, stderr)`, `self.backup_of(xuid)` and `self.add_game(package)`. `write_user_dir()` can set `etags=`, `states=` and `sync_flags=`.
- **Prove each new test can fail.** Temporarily break the line it's about, check that a test fails, then restore it. Several gaps in the suite were found this way, including a test that passed for the wrong reason.
- **Keep the fixtures independent:** `tests/fixtures.py` writes the save format byte by byte, deliberately not with `wgs.py`. Don't "simplify" it to use gss's own writer.
- **Changes to `extract.py` must match the original.** Handlers were ported from [XGP-save-extractor](https://github.com/Z1ni/XGP-save-extractor) and verified byte for byte against its `main.py`. Keep the behaviour identical unless the change is a deliberate fix, and say so in the commit.
- **After packaging changes:** rebuild `gss.exe` and run `packaging/smoke_test.py` on it, ideally with Python 3.10, which CI uses.

## Pitfalls that have already bitten this project

- **`gss.py` hides the `gss` package.** Any `sys.path` with the repository root ahead of `src/` makes `import gss` load `gss.py`. Put `src` first, as `packaging/smoke_test.py` does. PyInstaller must start from `packaging/gss_exe.py`: a first build from `gss.py` produced an `.exe` that couldn't start.
- **Agent shells may set `NoDefaultCurrentDirectoryInExePath=1`.** Command Prompt then won't run `gss` from the current folder, which normal users' Command Prompts do. Clear that variable before testing how a user's shell behaves.
- **Command Prompt and PowerShell differ.** In PowerShell, `gss` and `gss.exe` don't run from the current folder; only `.\gss` does. A quoted path needs `&` in front (`& "C:\...\gss.exe" list`). When testing a PowerShell command, run it from a `.ps1` file: passing it through `powershell -Command "..."` strips quotes and hides syntax errors.
- **Shell quoting when testing cmd:** `%VAR%` is expanded before `set VAR=...` takes effect on the same line.
- **`games.json` isn't alphabetical.** It's grouped by handler, under `//` comment headings. Add entries to their handler's group.
- **The version lives in two places:** `pyproject.toml` and `src/gss/__init__.py`. The release workflow's smoke test fails if they don't match the tag.
- **PCGamingWiki blocks automated fetches (HTTP 403).** Don't invent save paths or cloud-save behaviour. Say what you couldn't verify.
- **"LF will be replaced by CRLF" warnings from git are harmless** on Windows.

## Privacy

- **Never commit real Xbox account IDs (XUIDs)**, Windows user names, save files, backups or `ownerChangedID`s. Use the made-up IDs the project already uses:
  - account A: `2535412345678901` (hex `000901F1B0392C35`)
  - account B: `2535498765432109` (hex `00090205CF3DF52D`)
- **Real output in documentation** (`gss list` or `gss status` from the user's PC) must have XUIDs and user names replaced first. The repository's history was rewritten once to remove real XUIDs, so don't reintroduce them.
- **Before committing, search the diff** for 16-digit numbers starting with `2535` and for `000901`-style hex IDs that aren't the fake ones.

## Documentation

Keep these in step with behaviour changes, in the same commit:

| File | Audience | Update when |
|---|---|---|
| [README.md](README.md) | Non-technical players | Commands, options, output, install or troubleshooting change |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Human contributors | Setup, structure, rules, testing or release process change |
| [SECURITY.md](SECURITY.md) | Security reporters | Protections or reporting change |
| AGENTS.md | AI agents | Any of the above, or a new pitfall |

**README rules:**
- **Commands are written as `gss ...`**, the `gss.exe` form. The Python route says to type `python gss.py` instead.
- **Example output must be real output**, run on fake or sandboxed saves, with IDs anonymized.
- **Only list a game as tested** (the README's [tested games](README.md#tested-games) table) when the **user** has checked it end to end in-game. Never because a unit test or sandbox run passed.
- **Check every command and option you document** against `gss <command> --help`, and every in-page link against a real heading.

## Commits, branches and releases

- **Commit messages:** an imperative summary line ("Add …", "Fix …", "Reject …"), a blank line, then a body that explains *what* and *why*. Use one topic per commit, and split code changes from documentation changes.
- **Only commit or push when the user asks.** Pushing publishes to GitHub. Never force-push unless the user explicitly asks.
- **Releases follow Semantic Versioning:**
  - fixes: patch release
  - new commands, options or games: minor release
  - docs only: no release
- **Never move or re-create a pushed tag.** The release steps, which publishing triggers the `gss.exe` build from, are in [CONTRIBUTING.md](CONTRIBUTING.md#releases).

## Before you finish

- [ ] `python -m unittest` passes, and ideally `py -3.10 -m unittest` too
- [ ] New tests fail when the change is reverted
- [ ] The user's real saves are unchanged, if you ran gss on this PC
- [ ] README, CONTRIBUTING.md, SECURITY.md and this file are updated where behaviour changed
- [ ] No real XUIDs, user names or save data in the diff
- [ ] No `__pycache__`, `build/`, `dist/` or `*.egg-info` left behind
- [ ] Your summary says what you verified, and what you couldn't (for example, in-game behaviour)
