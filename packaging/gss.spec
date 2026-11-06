# PyInstaller build of gss.exe: a single file that runs without Python installed.
#
#   python -m pip install pyinstaller==6.11.1
#   python -m PyInstaller packaging/gss.spec
#
# The result is dist/gss.exe. GitHub Actions runs this for every release (.github/workflows/release.yml).

import re
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

root = Path(SPECPATH).parent  # noqa: F821 (SPECPATH is set by PyInstaller)
version = re.search(r'__version__ = "([^"]+)"', (root / "src" / "gss" / "__init__.py").read_text()).group(1)
numbers = tuple(int(n) for n in re.findall(r"\d+", version)[:3]) + (0,)

# Shown in File Explorer under Properties > Details
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo([
            StringTable("040904B0", [
                StringStruct("CompanyName", "gamepass-save-syncer contributors"),
                StringStruct("FileDescription", "gamepass-save-syncer: copy Xbox Game Pass saves between Xbox accounts"),
                StringStruct("FileVersion", version),
                StringStruct("InternalName", "gss"),
                StringStruct("LegalCopyright", "MIT License"),
                StringStruct("OriginalFilename", "gss.exe"),
                StringStruct("ProductName", "gamepass-save-syncer"),
                StringStruct("ProductVersion", version),
            ])
        ]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

a = Analysis(
    [str(root / "packaging" / "gss_exe.py")],
    pathex=[str(root / "src")],
    # games.json is read from next to gss/games.py
    datas=[(str(root / "src" / "gss" / "games.json"), "gss")],
    excludes=["tkinter", "unittest", "pydoc", "test"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="gss",
    console=True,
    # UPX compression makes antivirus false positives more likely
    upx=False,
    version=version_info,
)
