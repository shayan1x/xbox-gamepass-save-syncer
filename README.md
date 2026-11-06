<div align="center">

# gamepass-save-syncer

### Copy your Xbox Game Pass saves from one Xbox account to another.

Your progress belongs to you, not to one profile. **gss** moves a game's saves between Xbox accounts on the same PC, so Xbox cloud sync **keeps** them instead of overwriting them.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/windows/)
[![Windows 10 | 11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4?logo=windows&logoColor=white)](#requirements)
[![No dependencies](https://img.shields.io/badge/dependencies-none-success)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

[**Quick start**](#quick-start) · [**Copy a save**](#copy-a-save-to-another-xbox-account) · [Features](#features) · [FAQ](#faq) · [How it works](#how-it-works)

</div>

```console
> python gss.py copy --game "dark ages" --from 2535412345678901 --to 2535498765432109

  Game:        DOOM: The Dark Ages
  From:        2535412345678901
  To:          2535498765432109
  Folder:      C:\Users\you\AppData\Local\Packages\BethesdaSoftworks.ProjectTitan_3275kfvn8vcwc\SystemAppData\wgs\00090205CF3DF52D_00000000000000000000000071672517
    GAME-AUTOSAVE1: replaced, uploaded to the cloud
    PROFILE: replaced, uploaded to the cloud
  The current saves in that folder are backed up first.
  Close the game first. The next time it starts, Xbox uploads these saves to the
  account's cloud storage. If it reports a sync conflict, choose the save on this device.
  Copy these saves? [y/N] y
  Previous saves of account 2535498765432109 backed up to backups\doom_the_dark_ages_2535498765432109_before_restore_2026-01-15_18-30-00.zip

Copied and checked: C:\Users\you\AppData\Local\Packages\BethesdaSoftworks.ProjectTitan_3275kfvn8vcwc\SystemAppData\wgs\00090205CF3DF52D_00000000000000000000000071672517
Start the game on the target account to upload the saves to its cloud storage.
```

---

## Why?

You played 40 hours on one Xbox account and now want that progress on another, for example a new profile, or a family member's. The Xbox app has no way to do that, and copying the save files by hand **doesn't work**: the next time the game starts, Xbox sees the files as out of date and quietly downloads the old cloud save over them.

**gss** writes the copied saves the way Xbox expects a save made on this PC. They keep the target account's own cloud sync information and are marked as changed, so Xbox **uploads** them to the target account's cloud storage instead of replacing them. It also backs up whatever it replaces first, so every change can be undone.

> [!NOTE]
> Tested end to end, including the cloud upload, with **DOOM: The Dark Ages**. Copy works with **any** Game Pass game that uses Xbox cloud saves, because it never needs to understand the save files themselves.

---

## Features

| | Command | What it does |
|---|---|---|
| ⭐ | **`gss copy`** | **Copy a game's saves from one Xbox account to another, kept by cloud sync** |
| 🔍 | `gss list` | Show games with saves, Xbox account IDs and your backups |
| ☁️ | `gss status` | See whether each save is synced with the cloud, waiting, or in trouble |
| 💾 | `gss backup` | Back up any game's saves to a verified ZIP file |
| ⏪ | `gss restore` | Restore a backup, to the same account or another one |
| 🧹 | `gss reset` | Start a game from scratch for one account, in the cloud too |
| 🎮 | `gss extract` | Convert saves for the Steam/Epic version of [supported games](src/gss/games.json) |

**Built to be safe:**
- **Undo:** every command that changes saves backs them up first, and puts them back if anything fails.
- **Checksums:** backups carry a checksum for every file, checked on writing and before restoring.
- **Sync-aware:** it refuses to touch a half-synced folder, and shows you what will change before asking.
- **No dependencies:** only Python's standard library.

---

## Quick start

#### Requirements

- Windows 10 or 11, with games installed from the **Xbox app** (PC Game Pass).
- **Python 3.10 or newer** from [python.org](https://www.python.org/downloads/windows/). In the installer, tick **"Add python.exe to PATH"**.

#### Install

1. Download this project (the green **Code** button → **Download ZIP**) and unzip it.
2. Open the unzipped folder in File Explorer, click the address bar, type `cmd` and press **Enter**. A Command Prompt opens in that folder.
3. Check that it works:

   ```bash
   python gss.py --version
   ```

<details>
<summary>Prefer a <code>gss</code> command that works in any folder?</summary>

```bash
pip install .
```

Then type `gss` instead of `python gss.py`, for example `gss list`.
</details>

#### Copy a save in 3 commands

```bash
python gss.py list
```
```bash
python gss.py copy --game "<game>" --from <XUID with the progress> --to <XUID to copy to>
```
```bash
python gss.py status --user <XUID you copied to>
```

The full walkthrough is just below.

---

## Copy a save to another Xbox account

Say account **A** has the progress you want, and you want it on account **B**.

1. **Account B must have started the game on this PC at least once**, so it has its own save folder:
   1. Sign in to the Xbox app as B.
   2. Start the game and wait for the main menu.
   3. Quit the game.
2. **Close the game.**
3. Find the game and both accounts:

   ```bash
   python gss.py list
   ```

   ```
     GAME                 ID                                            XUID              XUID (HEX)        LAST SAVED
     DOOM: The Dark Ages  BethesdaSoftworks.ProjectTitan_3275kfvn8vcwc  2535412345678901  000901F1B0392C35  2026-01-15 17:42
     DOOM: The Dark Ages  BethesdaSoftworks.ProjectTitan_3275kfvn8vcwc  2535498765432109  00090205CF3DF52D  2026-01-14 21:15
   ```

   Each row is one account's saves for one game. The **XUID** is the account's ID.

   > **Which XUID is which account?** The gamertag is shown for the account signed in to the Xbox app. **LAST SAVED** helps too: it's the account you played on last.

4. Copy from A to B:

   ```bash
   python gss.py copy --game "dark ages" --from 2535412345678901 --to 2535498765432109
   ```

   `--game` takes the game's ID or any part of its name. gss shows what will be replaced and asks `Copy these saves? [y/N]`. Type `y`.
5. Sign in to the Xbox app as **B** and start the game. If Xbox shows a **sync conflict**, choose the save **on this device**.
6. Check your progress, **quit the game normally**, and give the Xbox app a minute to upload.
7. Confirm the upload:

   ```bash
   python gss.py status --user 2535498765432109
   ```

   Every slot should say **synced**, and the last line `OK: Everything is synced with the cloud.`

✅ **Account A is never changed.** Account B's previous saves are kept in `backups\<game>_<XUID of B>_before_restore_<date>.zip`. To undo the copy, [restore that file](#restore-and-undo).

<details>
<summary>Copy later, or keep the copy as a file</summary>

`backup` with `--to-xuid` makes a backup that restores to the other account by default:

```bash
python gss.py backup --game "dark ages" --user <XUID of A> --to-xuid <XUID of B>
```
```bash
python gss.py restore backups\<that file>.zip
```
</details>

---

## More commands

### Check sync status

```bash
python gss.py status
```

```
DOOM: The Dark Ages - account 2535498765432109
  SAVE SLOT       STATUS                       SIZE    SAVED
  GAME-AUTOSAVE1  changed, waiting for upload  187 KB  2026-01-15 18:30
  PROFILE         changed, waiting for upload  36 KB   2026-01-15 18:30
  Waiting: Not everything is uploaded yet. Start the game on this account and quit it normally to sync with the cloud.
```

- **Waiting:** a copy, restore or reset hasn't reached the cloud yet.
- **`!!` lines:** the saves are half-synced (close the game and wait a minute), or Xbox may have found a sync conflict.
- **Slot names:** the first column has the names [`reset --save`](#start-a-game-from-scratch) takes.
- **Filters:** narrow it down with `--game` and `--user`.

### Back up

```bash
python gss.py backup
```

This backs up every game for every account, into ZIP files in the `backups` folder. Narrow it down with `--game` and/or `--user`. Each backup is checked right after it's written. Keep copies somewhere off this PC if you want them safe from a disk failure.

### Restore and undo

1. **Close the game.**
2. Restore the file:

   ```bash
   python gss.py restore backups\doom_the_dark_ages_2535412345678901_2026-01-15_18-05-00.zip
   ```

   Type `python gss.py restore backups\` and press **Tab** to cycle through the file names.
3. Type `y` to confirm.
4. Start the game. If Xbox shows a sync conflict, choose the save **on this device**.

Add `--to-xuid <XUID>` to restore into a different account. A restore, copy or reset always saves what it replaces as a `..._before_restore_...zip` or `..._before_reset_...zip` backup first. Restoring that file undoes the change.

### Start a game from scratch

```bash
python gss.py reset --game "dark ages" --user 2535498765432109
```

This deletes that account's saves for the game, on this PC **and** in the cloud. The next launch starts from the very beginning, and other accounts aren't affected.

To keep some save slots, such as settings, reset only the ones you name. `status` lists the slot names:

```bash
python gss.py reset --game "dark ages" --user 2535498765432109 --save GAME-AUTOSAVE1
```

> A few games also keep progress outside their Xbox saves, for example in Documents or on their own servers. Reset only clears the Xbox saves.

### Use your saves on Steam or Epic

```bash
python gss.py extract
```

For every game in the [supported list](src/gss/games.json), this writes a ZIP to the `extracted` folder, with the files the way the Steam/Epic version expects them. Look up the Steam/Epic save folder on [PCGamingWiki](https://www.pcgamingwiki.com/) ("Save game data location"), back it up, and copy the files in.

The list and its test status come from [XGP-save-extractor](https://github.com/Z1ni/XGP-save-extractor), which also tracks [games that can't be converted](https://github.com/Z1ni/XGP-save-extractor#incompatible-games).

---

## FAQ

<details>
<summary><b>Does copy work for my game?</b></summary>

Copy works for every Game Pass game whose saves `gss list` shows. gss never reads or changes the save files themselves, so it doesn't need to know the game. Only `extract` is limited to the games in [games.json](src/gss/games.json). It's been tested end to end with DOOM: The Dark Ages.
</details>

<details>
<summary><b>Can I copy to an account on another PC?</b></summary>

Not directly: the target account needs a save folder on the PC where you restore. Back up with `--to-xuid <their XUID>`, move the ZIP to their PC (with gss), and restore it there after they've started the game once.
</details>

<details>
<summary><b>Xbox replaced my copied or restored save with the old one.</b></summary>

Either the game was running during the copy, or the **cloud** save was chosen in a sync conflict. Close the game, run the copy again (it's safe to repeat), and choose the save **on this device** when asked. `gss status` shows whether the upload went through.
</details>

<details>
<summary><b>"Xbox account … has no … saves on this PC yet"</b></summary>

The account you're copying to has to start the game on this PC once (see [step 1](#copy-a-save-to-another-xbox-account)). gss needs that account's own save folder to keep Xbox cloud sync happy.
</details>

<details>
<summary><b>"The saves are incomplete" / "Xbox may still be syncing"</b></summary>

The game is running or Xbox is in the middle of a sync. Close the game, wait a minute, and try again.
</details>

<details>
<summary><b>Will this get my account banned?</b></summary>

gss doesn't modify games or save contents. It moves your own save files between your own accounts' folders, the same files Xbox syncs anyway. Online games may have their own rules about shared progress; check them if that matters to you. Use at your own risk.
</details>

<details>
<summary><b>Other questions</b></summary>

- **My game isn't in `list`:** it has no Xbox saves on this PC yet. Start it once and save. Steam/Epic games aren't Xbox saves.
- **`extract` skips my game:** it isn't in the conversion list. Copy, backup, restore and reset still work. To ask for support, open an issue at [XGP-save-extractor](https://github.com/Z1ni/XGP-save-extractor/issues/new/choose).
- **GAMERTAG shows "-":** only the account signed in to the Xbox app has a known gamertag.
- **`python` is not recognized:** reinstall Python with "Add python.exe to PATH" ticked, then open a new Command Prompt.
</details>

---

## How it works

Xbox keeps each account's saves for a game in
`%LOCALAPPDATA%\Packages\<game ID>\SystemAppData\wgs\<XUID in hex>_<…>\`.
A file there, `containers.index`, records each save and the cloud version it was last synced at.

**Why copying files by hand fails:** the copied index still records the *source* account's cloud versions, with every save marked as synced. On the next launch, Xbox compares those with the *target* account's cloud, finds them different, and treats the cloud as newer. It downloads the old save over your copy, without asking.

**What gss does instead:** it rebuilds the target's index. Each copied save:
- keeps the **target account's** cloud version and sync identity
- is marked **changed on this PC**
- keeps its record of what the cloud last had, so Xbox can tell exactly which files changed

That's how Xbox records a save the game made on this PC, so Xbox **uploads** it.

The other commands use the same idea:
- **Restore** is a copy from a ZIP file.
- **Reset** marks saves as **deleted** instead of removing the files, so the deletion reaches the cloud too.
- **Status** reads these sync states back to you.

The save format details come from the [Xodus wiki](https://github.com/xodus-gaming/xodus/wiki/savefileformat) and from checking real saves before and after Xbox syncs.

---

## Command reference

| Command | What it does |
|---|---|
| `gss copy --game GAME --from XUID --to XUID` | Copy a game's saves from one Xbox account to another |
| `gss list` | Show games with saves, Xbox account IDs (XUIDs) and backups |
| `gss status` | Show each save slot and whether it's synced with the Xbox cloud |
| `gss backup` | Back up saves to ZIP files |
| `gss restore FILE` | Restore a backup |
| `gss reset --game GAME --user XUID` | Delete an account's saves for a game, so it starts from scratch |
| `gss extract` | Convert saves for the Steam/Epic version of a game |

| Option | Works with | Meaning |
|---|---|---|
| `--game GAME` | all but restore | Only this game: its ID or part of its name (required for copy and reset) |
| `--from XUID`, `--to XUID` | copy | The account to copy from (not changed), and the one to copy to |
| `--user XUID` | list, status, backup, reset, extract | Only this Xbox account (required for reset) |
| `--to-xuid XUID` | backup, restore | Restore to this Xbox account instead |
| `--save NAME` | reset | Only reset this save slot; can be given more than once |
| `-o DIR`, `--output DIR` | backup, restore, copy, reset, extract | Where to write ZIP files (`backups`, or `extracted` for extract) |
| `--backups DIR` | list | Where to look for backups (default `backups`) |
| `-y`, `--yes` | restore, copy, reset | Don't ask for confirmation |

XUIDs can be decimal (`2535412345678901`) or hex (`000901F1B0392C35`). Every command has `--help`. For scripts, `gss status` exits with **0** when everything is synced, **2** when something is waiting, and **3** when there's a problem.

---

## Contributing

Bug reports, tested games and pull requests are welcome.

- **Report a problem:** include the output of `gss status` for the game. It shows the sync state without any save contents.
- **Add a game for `extract`:** add it to [`src/gss/games.json`](src/gss/games.json) with one of the handlers in [`src/gss/extract.py`](src/gss/extract.py).
- **Run the tests:** they build fake saves in a temp folder and never touch real ones.

  ```bash
  python -m unittest
  ```

<details>
<summary>Code layout</summary>

| Module | Contents |
|---|---|
| `wgs.py` | The Xbox save format (`containers.index`, `container.N`) |
| `restore.py` | Restores, and copies between accounts |
| `edit.py` | Shared steps for changing saves so Xbox cloud sync accepts them |
| `reset.py` | Resets |
| `status.py` | Sync status of an account's saves |
| `backup.py` | Backups |
| `extract.py` | Steam/Epic conversion |
| `discovery.py`, `accounts.py`, `games.py` | Finding saves, accounts and game names |
| `cli.py` | The `gss` command |
</details>

---

## Credits and license

[MIT License](LICENSE).

The Steam/Epic conversion and the game list come from [XGP-save-extractor](https://github.com/Z1ni/XGP-save-extractor) by Mark Mäkinen and its contributors. The save format documentation comes from the [Xodus wiki](https://github.com/xodus-gaming/xodus/wiki/savefileformat) and from [@snoozbuster's research](https://github.com/goatfungus/NMSSaveEditor/issues/306).

<sub>gss is an independent project, not affiliated with or endorsed by Microsoft. Xbox and Game Pass are trademarks of Microsoft Corporation. Use at your own risk, and keep backups of saves you care about.</sub>
