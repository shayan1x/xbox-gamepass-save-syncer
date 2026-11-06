"""The gss command: list, status, backup, restore, copy, reset and extract Xbox Game Pass for PC saves."""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from gss import GssError, __version__
from gss.accounts import gamertag, parse_xuid
from gss.backup import create_backup, read_backup
from gss.discovery import default_packages_root, discover
from gss.extract import extract_save
from gss.fsutil import list_files
from gss.games import fallback_name, game_matches, load_catalog
from gss.reset import reset_saves
from gss.status import CONFLICT, INCOMPLETE, PENDING, SYNCED, save_status
from gss.restore import DEFAULT_BACKUP_DIR, RestorePreview, copy_saves, restore_backup

DEFAULT_EXTRACT_DIR = Path("extracted")


# ---------------------------------------------------------------- output helpers


def print_table(headers: List[str], rows: List[List[str]], indent: str = "  ") -> None:
    widths = [max(len(str(c)) for c in col) for col in zip(headers, *rows)]
    fmt = indent + "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers).rstrip())
    print(fmt.format(*("-" * w for w in widths)).rstrip())
    for row in rows:
        print(fmt.format(*row).rstrip())


def local_time(dt: datetime | None) -> str:
    return dt.astimezone().strftime("%Y-%m-%d %H:%M") if dt else "?"


def account(xuid: int, packages_root: Path) -> str:
    tag = gamertag(xuid, packages_root)
    return f"{xuid} ({tag})" if tag else str(xuid)


def xuid_arg(text: str) -> int:
    try:
        return parse_xuid(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def no_saves_message(args) -> str:
    return "No saves found" + (" matching the filters" if args.game or args.user is not None else "")


# ---------------------------------------------------------------- commands


def cmd_list(args, packages_root: Path) -> int:
    names, saves = discover(packages_root, args.game, args.user)

    print("Games with Xbox saves")
    print("  Pass the ID to --game, and the XUID to --user or --to-xuid.\n")
    if saves:
        rows = []
        for s in saves:
            files = [p for p in list_files(s.path).values()]
            last_saved = datetime.fromtimestamp(max(p.stat().st_mtime for p in files))
            rows.append([
                names.get(s.package) or fallback_name(s.package),
                s.package,
                str(s.xuid),
                f"{s.xuid:016X}",
                last_saved.strftime("%Y-%m-%d %H:%M"),
            ])
        print_table(["GAME", "ID", "XUID", "XUID (HEX)", "LAST SAVED"], rows)

        accounts: Dict[int, int] = {}
        for s in saves:
            accounts[s.xuid] = accounts.get(s.xuid, 0) + 1
        print("\nXbox accounts")
        print_table(
            ["XUID", "XUID (HEX)", "GAMERTAG", "GAMES"],
            [[str(x), f"{x:016X}", gamertag(x, packages_root) or "-", str(n)] for x, n in sorted(accounts.items())],
        )
    else:
        print("  " + no_saves_message(args))

    backup_dir: Path = args.backups
    zips = sorted(backup_dir.glob("*.zip")) if backup_dir.is_dir() else []
    print(f"\nBackups in {backup_dir.resolve()} (pass the file to restore)")
    rows = []
    for z in zips:
        try:
            b = read_backup(z)
        except GssError as e:
            rows.append([z.name, "-", "-", "-", f"INVALID: {e}"])
            continue
        if args.game and not game_matches(args.game, b.package, {**names, b.package: b.game}):
            continue
        if args.user is not None and args.user not in (b.xuid, b.source_xuid):
            continue
        restores_to = str(b.xuid) + (f" (from {b.source_xuid})" if b.source_xuid != b.xuid else "")
        rows.append([z.name, b.game, restores_to, local_time(b.created), "OK"])
    if rows:
        print_table(["FILE", "GAME", "RESTORES TO XUID", "CREATED", "CHECK"], rows)
    else:
        print("  None" + (" matching the filters" if zips else ""))
    return 0


def format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def cmd_status(args, packages_root: Path) -> int:
    names, saves = discover(packages_root, args.game, args.user)
    if not saves:
        print(no_saves_message(args))
        return 1
    worst = SYNCED
    order = [SYNCED, PENDING, CONFLICT, INCOMPLETE]
    for i, save in enumerate(saves):
        if i:
            print()
        status = save_status(save.path)
        worst = max(worst, status.summary, key=order.index)
        print(f"{names.get(save.package) or fallback_name(save.package)} - account {account(save.xuid, packages_root)}")
        if status.slots:
            print_table(
                ["SAVE SLOT", "STATUS", "SIZE", "SAVED"],
                [[s.name, s.describe(), format_size(s.size), local_time(s.saved)] for s in status.slots],
            )
        marker = {SYNCED: "OK: ", PENDING: "Waiting: ", CONFLICT: "!! ", INCOMPLETE: "!! "}[status.summary]
        print(f"  {marker}{status.message}")
    # Exit code for scripts: 0 all synced, 2 something waiting, 3 a problem
    return {SYNCED: 0, PENDING: 2}.get(worst, 3)


def cmd_backup(args, packages_root: Path) -> int:
    names, saves = discover(packages_root, args.game, args.user)
    if not saves:
        print(no_saves_message(args))
        return 1
    if args.to_xuid is not None:
        packages = [s.package for s in saves]
        if len(packages) != len(set(packages)):
            raise GssError(
                "--to-xuid needs a single source account per game; pick one with --user "
                f"(found: {', '.join(sorted({str(s.xuid) for s in saves}))})"
            )

    failed = 0
    for save in saves:
        print(f"{names.get(save.package) or fallback_name(save.package)} - account {account(save.xuid, packages_root)}")
        try:
            backup = create_backup(save, args.output, names, args.to_xuid)
            note = f" (restores to account {args.to_xuid})" if args.to_xuid is not None else ""
            print(f"  -> {backup.path}{note}")
        except GssError as e:
            failed += 1
            print(f"  !! {e}")
    print(f"\n{len(saves) - failed} of {len(saves)} backup(s) written to {args.output.resolve()}")
    return 1 if failed else 0


def ask(args, question: str) -> bool:
    if args.yes:
        return True
    return input(f"  {question} [y/N] ").strip().lower() in ("y", "yes")


def restore_confirmation(args, packages_root: Path, question: str, copying: bool = False):
    """The confirm() for restore and copy: show what will change, then ask."""

    def confirm(preview: RestorePreview) -> bool:
        b = preview.backup
        print(f"  Game:        {b.game}")
        if copying:
            print(f"  From:        {account(b.source_xuid, packages_root)}")
            print(f"  To:          {account(preview.target_xuid, packages_root)}")
        else:
            print(f"  Backup of:   {account(b.source_xuid, packages_root)}, made {local_time(b.created)}")
            print(f"  Restore to:  {account(preview.target_xuid, packages_root)}")
        print(f"  Folder:      {preview.target_dir}")
        for change in preview.changes:
            print(f"    {change.save}: {change.describe()}")
        print("  The current saves in that folder are backed up first.")
        print("  Close the game first. The next time it starts, Xbox uploads these saves to the")
        print("  account's cloud storage. If it reports a sync conflict, choose the save on this device.")
        return ask(args, question)

    return confirm


def find_one_save(packages_root: Path, game: str, xuid: int):
    """The saves of exactly one game for one account, or an error saying why not."""
    names, saves = discover(packages_root, game, xuid)
    if not saves:
        raise GssError(f"No saves found for account {xuid} matching --game {game!r}. See 'gss list'.")
    packages = sorted({s.package for s in saves})
    if len(packages) > 1:
        matches = ", ".join(f"{names.get(p) or fallback_name(p)} ({p})" for p in packages)
        raise GssError(f"--game {game!r} matches more than one game: {matches}. Use the game's ID.")
    return names, saves[0]


def cmd_restore(args, packages_root: Path) -> int:
    names = {pkg: e.name for pkg, e in load_catalog().items()}
    confirm = restore_confirmation(args, packages_root, "Continue?")
    result = restore_backup(args.backup, packages_root, names, args.to_xuid, args.output, confirm)
    print(f"  Previous saves backed up to {result.safety_backup}")
    print(f"\nRestored and checked: {result.target_dir}")
    return 0


def cmd_copy(args, packages_root: Path) -> int:
    names, save = find_one_save(packages_root, args.game, args.from_xuid)
    confirm = restore_confirmation(args, packages_root, "Copy these saves?", copying=True)
    result = copy_saves(save, args.to_xuid, packages_root, names, args.output, confirm)
    print(f"  Previous saves of account {args.to_xuid} backed up to {result.safety_backup}")
    print(f"\nCopied and checked: {result.target_dir}")
    print("Start the game on the target account to upload the saves to its cloud storage.")
    return 0


def cmd_reset(args, packages_root: Path) -> int:
    names, save = find_one_save(packages_root, args.game, args.user)
    game = names.get(save.package) or fallback_name(save.package)

    def confirm(preview) -> bool:
        print(f"  Game:     {game}")
        print(f"  Account:  {account(save.xuid, packages_root)}")
        print(f"  Folder:   {save.path}")
        for change in preview.changes:
            print(f"    {change.save}: {change.describe()}")
        print("  The game will start from scratch for this account. The saves are backed up first,")
        print("  so you can undo this with 'gss restore'. Close the game before continuing.")
        return ask(args, "Reset these saves?")

    result = reset_saves(save, names, args.save, args.output, confirm)
    print(f"  Previous saves backed up to {result.safety_backup}")
    print("\nReset done. The next time the game starts, Xbox removes these saves from the cloud too.")
    print("If Xbox reports a sync conflict, choose the save on this device.")
    return 0


def cmd_extract(args, packages_root: Path) -> int:
    catalog = load_catalog()
    names, saves = discover(packages_root, args.game, args.user)
    supported = [s for s in saves if s.package in catalog]
    if not supported:
        if saves:
            print("None of these games are in the list of games whose saves can be converted for Steam/Epic:")
            for package in sorted({s.package for s in saves}):
                print(f"  - {names.get(package) or fallback_name(package)}")
        else:
            print(no_saves_message(args))
        return 1

    failed = 0
    for save in supported:
        entry = catalog[save.package]
        print(f"{entry.name} - account {account(save.xuid, packages_root)}")
        try:
            result = extract_save(save, entry, args.output)
        except GssError as e:
            failed += 1
            print(f"  !! {e}")
            continue
        if result is None:
            print("  No save files")
            continue
        for name in result.files:
            print(f"  - {name}")
        print(f"  -> {result.path}")
    skipped = sorted({s.package for s in saves} - set(catalog))
    if skipped:
        print("\nSkipped, not in the list of games whose saves can be converted:")
        for package in skipped:
            print(f"  - {names.get(package) or fallback_name(package)}")
    return 1 if failed else 0


# ---------------------------------------------------------------- argument parsing


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=program_name(),
        description="gamepass-save-syncer: back up, restore and move Xbox Game Pass for PC saves "
        "between Xbox accounts, and convert them for Steam/Epic.",
    )
    parser.add_argument("--version", action="version", version=f"gss {__version__}")
    parser.add_argument("--packages-root", type=Path, default=None, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def filters(p, what: str):
        p.add_argument("--game", help=f"only {what} this game: its ID from 'gss list', or part of its name")
        p.add_argument("--user", type=xuid_arg, metavar="XUID", help=f"only {what} this Xbox account")

    ls = sub.add_parser("list", help="show games with saves, Xbox account IDs and backups")
    filters(ls, "show")
    ls.add_argument("--backups", type=Path, default=DEFAULT_BACKUP_DIR, metavar="DIR",
                    help="folder to look for backups in (default: backups)")
    ls.set_defaults(func=cmd_list)

    st = sub.add_parser("status", help="show save slots and whether they're synced with the Xbox cloud")
    filters(st, "show")
    st.set_defaults(func=cmd_status)

    b = sub.add_parser("backup", help="back up saves to ZIP files")
    filters(b, "back up")
    b.add_argument("--to-xuid", type=xuid_arg, metavar="XUID",
                   help="make the backup restore to this account instead (moves the save there)")
    b.add_argument("-o", "--output", type=Path, default=DEFAULT_BACKUP_DIR, metavar="DIR",
                   help="folder to write backups to (default: backups)")
    b.set_defaults(func=cmd_backup)

    r = sub.add_parser("restore", help="restore a backup, to the same or another Xbox account")
    r.add_argument("backup", type=Path, help="backup ZIP file")
    r.add_argument("--to-xuid", type=xuid_arg, metavar="XUID",
                   help="restore into this Xbox account instead of the one in the backup")
    r.add_argument("-o", "--output", type=Path, default=DEFAULT_BACKUP_DIR, metavar="DIR",
                   help="folder for the backup of the saves being replaced (default: backups)")
    r.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    r.set_defaults(func=cmd_restore)

    cp = sub.add_parser("copy", help="copy a game's saves from one Xbox account to another")
    cp.add_argument("--game", required=True, help="the game: its ID from 'gss list', or part of its name")
    cp.add_argument("--from", dest="from_xuid", required=True, type=xuid_arg, metavar="XUID",
                    help="the Xbox account to copy from (not changed)")
    cp.add_argument("--to", dest="to_xuid", required=True, type=xuid_arg, metavar="XUID",
                    help="the Xbox account to copy to (its saves are replaced)")
    cp.add_argument("-o", "--output", type=Path, default=DEFAULT_BACKUP_DIR, metavar="DIR",
                    help="folder for the backup of the saves being replaced (default: backups)")
    cp.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    cp.set_defaults(func=cmd_copy)

    rs = sub.add_parser("reset", help="delete an account's saves for a game, so it starts from scratch")
    rs.add_argument("--game", required=True, help="the game: its ID from 'gss list', or part of its name")
    rs.add_argument("--user", required=True, type=xuid_arg, metavar="XUID", help="the Xbox account")
    rs.add_argument("--save", action="append", metavar="NAME",
                    help="only reset this save slot (can be given more than once); default: all of them")
    rs.add_argument("-o", "--output", type=Path, default=DEFAULT_BACKUP_DIR, metavar="DIR",
                    help="folder for the backup made before resetting (default: backups)")
    rs.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    rs.set_defaults(func=cmd_reset)

    e = sub.add_parser("extract", help="convert saves to files for the Steam/Epic version of a game")
    filters(e, "extract")
    e.add_argument("-o", "--output", type=Path, default=DEFAULT_EXTRACT_DIR, metavar="DIR",
                   help="folder to write ZIP files to (default: extracted)")
    e.set_defaults(func=cmd_extract)
    return parser


def program_name() -> str:
    """How the user started gss, for usage examples: gss (installed or gss.exe) or python gss.py."""
    if not getattr(sys, "frozen", False) and sys.argv and sys.argv[0].lower().endswith(".py"):
        return "python gss.py"
    return "gss"


def opened_by_double_click() -> bool:
    """Whether Windows opened a console window just for gss, which closes as soon as gss exits."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        processes = (ctypes.c_uint * 4)()
        count = ctypes.windll.kernel32.GetConsoleProcessList(processes, len(processes))
    except (AttributeError, OSError):
        return False
    # Run from Command Prompt, the console is shared with cmd.exe. Opened by a double-click, gss
    # is alone in it, together with the launcher of a one-file PyInstaller build if it is gss.exe.
    alone = 2 if getattr(sys, "frozen", False) else 1
    return 0 < count <= alone


def show_welcome(parser: argparse.ArgumentParser) -> None:
    prog = program_name()
    print(f"gamepass-save-syncer {__version__}: copy, back up and restore Xbox Game Pass PC saves.\n")
    print("This is a command-line tool. Open Command Prompt in this folder and type a command, for example:\n")
    print("  See your games and Xbox account IDs:")
    print(f"    {prog} list")
    print("  Copy a game's saves to another Xbox account:")
    print(f'    {prog} copy --game "<game>" --from <ID> --to <ID>')
    print("  Check that saves are synced with the cloud:")
    print(f"    {prog} status\n")
    print("Tip: in File Explorer, click the address bar of this folder, type cmd and press Enter.")
    print("Guide: https://github.com/shayan1x/xbox-gamepass-save-syncer#readme\n")
    parser.print_help()


def main(argv: List[str] | None = None) -> int:
    # Game names can contain characters the console can't show; don't crash printing them
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = build_parser()
    if not (sys.argv[1:] if argv is None else argv):
        show_welcome(parser)
        if opened_by_double_click():
            input("\nPress Enter to close this window...")
        return 0
    args = parser.parse_args(argv)
    packages_root = args.packages_root or default_packages_root()
    try:
        return args.func(args, packages_root)
    except GssError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled", file=sys.stderr)
        return 130
