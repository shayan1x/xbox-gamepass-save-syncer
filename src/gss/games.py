"""Game names and the catalog of games whose saves can be converted for Steam/Epic (games.json)."""

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable

from gss import GssError

CATALOG_PATH = Path(__file__).with_name("games.json")
PACKAGE_FAMILY_RE = re.compile(r"^[A-Za-z0-9.\-]+_[a-z0-9]{13}$")


@dataclass(frozen=True)
class CatalogEntry:
    package: str
    name: str
    handler: str
    handler_args: Dict[str, Any] = field(default_factory=dict)


def load_catalog(path: Path = CATALOG_PATH) -> Dict[str, CatalogEntry]:
    """games.json as {package: entry}. Lines starting with // are comments."""
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads("\n".join(l for l in text.splitlines() if not l.lstrip().startswith("//")))
        return {
            g["package"]: CatalogEntry(g["package"], g["name"], g["handler"], g.get("handler_args") or {})
            for g in data["games"]
        }
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise GssError(f"Can't read the game list {path}: {e}") from e


def installed_display_names(packages: Iterable[str]) -> Dict[str, str]:
    """Ask Windows for the display names of installed packages, e.g. "Resident Evil Village".

    Returns {} where that isn't possible (no PowerShell, package not installed)."""
    families = sorted({p for p in packages if PACKAGE_FAMILY_RE.match(p)})
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not families or not powershell:
        return {}
    # Names are checked against PACKAGE_FAMILY_RE above, so they are safe to quote here
    names = ",".join(f"'{f}'" for f in families)
    script = (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
        f"$families = @({names}); "
        "$r = @{}; "
        "Get-AppxPackage | Where-Object { $families -contains $_.PackageFamilyName } | ForEach-Object { "
        "  try { $r[$_.PackageFamilyName] = ($_ | Get-AppxPackageManifest).Package.Properties.DisplayName } catch {} "
        "}; "
        "$r | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=30, check=True,
        )
        found = json.loads(result.stdout.decode("utf-8") or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    if not isinstance(found, dict):
        return {}
    return {
        pkg: name.strip()
        for pkg, name in found.items()
        if pkg in families and isinstance(name, str) and name.strip() and not name.startswith("ms-resource:")
    }


def fallback_name(package: str) -> str:
    """A readable stand-in when a game's name is unknown: the package name without its publisher hash."""
    return package.split("_")[0]


def game_matches(query: str, package: str, names: Dict[str, str]) -> bool:
    """Does --game QUERY select this package? Matches part of the package name or the game name."""
    q = query.lower()
    name = names.get(package)
    return q in package.lower() or (name is not None and q in name.lower())
