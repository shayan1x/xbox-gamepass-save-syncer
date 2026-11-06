"""Check that a built gss.exe works: python packaging/smoke_test.py dist/gss.exe [expected version]

Runs the exe on fake saves (made with the test fixtures), from a folder outside the project, so
nothing can come from the source tree by accident. Never touches real saves.
"""

import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# src must come first: the project folder's gss.py would otherwise hide the gss package
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from gss.accounts import user_dir_name  # noqa: E402
from tests.fixtures import PKG, SAVE_A, SAVE_B, SCID, XUID_A, XUID_B, write_user_dir  # noqa: E402


def run(exe: Path, cwd: Path, *args, expect: int = 0) -> str:
    result = subprocess.run([str(exe), *map(str, args)], cwd=cwd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=120, stdin=subprocess.DEVNULL)
    output = result.stdout + result.stderr
    if result.returncode != expect:
        raise SystemExit(f"FAILED: gss {' '.join(map(str, args))} exited with {result.returncode}, "
                         f"expected {expect}:\n{output}")
    return output


def check(condition: bool, what: str) -> None:
    if not condition:
        raise SystemExit(f"FAILED: {what}")
    print(f"ok  {what}")


def main() -> None:
    exe = Path(sys.argv[1]).resolve()
    if not exe.is_file():
        raise SystemExit(f"FAILED: {exe} doesn't exist")
    expected_version = sys.argv[2].lstrip("v") if len(sys.argv) > 2 else None
    work = Path(tempfile.mkdtemp(prefix="gss-smoke-"))
    try:
        local_exe = work / "gss.exe"
        shutil.copy2(exe, local_exe)
        packages = work / "Packages"
        wgs = packages / PKG / "SystemAppData" / "wgs"
        write_user_dir(wgs / user_dir_name(XUID_A, SCID), SAVE_A)
        write_user_dir(wgs / user_dir_name(XUID_B, SCID), SAVE_B)
        root = ["--packages-root", packages]

        version = run(local_exe, work, "--version").strip()
        check(version.startswith("gss "), f"--version prints {version!r}")
        if expected_version:
            check(version == f"gss {expected_version}", f"version matches the release ({expected_version})")

        check("This is a command-line tool" in run(local_exe, work), "no arguments shows the guide")

        out = run(local_exe, work, *root, "list", "--backups", work / "backups")
        check("DOOM: The Dark Ages" in out and str(XUID_B) in out, "list finds the saves, named from games.json")

        out = run(local_exe, work, *root, "status")
        check("OK: Everything is synced" in out, "status reads the save index")

        run(local_exe, work, *root, "backup", "-o", work / "backups")
        check(len(list((work / "backups").glob("*.zip"))) == 2, "backup writes one ZIP per account")

        run(local_exe, work, *root, "copy", "--game", "dark ages", "--from", XUID_A, "--to", XUID_B, "-y",
            "-o", work / "backups")
        out = run(local_exe, work, *root, "status", "--user", XUID_B, expect=2)
        check("changed, waiting for upload" in out, "copy marks the copied saves for upload")

        run(local_exe, work, *root, "extract", "--user", XUID_B, "-o", work / "extracted")
        [z] = (work / "extracted").glob("*.zip")
        with zipfile.ZipFile(z) as zf:
            files = {n: zf.read(n) for n in zf.namelist()}
        expected = {f"{c}/{f}": d for c, fs in SAVE_A.items() for f, d in fs.items()}
        check(files == expected, "extract converts the copied saves with the games.json handler")

        out = run(local_exe, work, *root, "copy", "--game", "x", "--from", "nope", "--to", "1", expect=2)
        check("not a valid Xbox account ID" in out, "bad input gets a clear message")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("gss.exe works")


if __name__ == "__main__":
    main()
