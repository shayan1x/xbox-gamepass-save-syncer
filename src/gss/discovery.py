"""Finding Xbox saves on this PC."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from gss import GssError
from gss.accounts import split_user_dir_name
from gss.games import game_matches, installed_display_names, load_catalog
from gss.wgs import INDEX_NAME

PACKAGES_ROOT_ENV = "GSS_PACKAGES_ROOT"


def default_packages_root() -> Path:
    """Where Windows keeps app data: %LOCALAPPDATA%\\Packages (or $GSS_PACKAGES_ROOT, for testing)."""
    override = os.environ.get(PACKAGES_ROOT_ENV)
    if override:
        return Path(override)
    return Path(os.path.expandvars(r"%LOCALAPPDATA%\Packages"))


def wgs_dir(packages_root: Path, package: str) -> Path:
    return packages_root / package / "SystemAppData" / "wgs"


@dataclass
class UserSave:
    """One Xbox account's saves for one game."""

    package: str
    xuid: int
    scid: str
    path: Path


def find_saves(packages_root: Path, user: int | None = None) -> List[UserSave]:
    """Every account's saves for every game, sorted by package then XUID."""
    if not packages_root.is_dir():
        raise GssError(f"Packages folder not found: {packages_root}")
    saves = []
    for pkg_dir in sorted(packages_root.iterdir()):
        wgs = pkg_dir / "SystemAppData" / "wgs"
        if not wgs.is_dir():
            continue
        for entry in sorted(wgs.iterdir()):
            # Skip the "t" temp folder and the Xbox app's own backup folders
            if not entry.is_dir() or entry.name == "t" or "backup" in entry.name.lower():
                continue
            parsed = split_user_dir_name(entry.name)
            if parsed is None or not (entry / INDEX_NAME).is_file():
                continue
            xuid, scid = parsed
            if user is not None and xuid != user:
                continue
            saves.append(UserSave(pkg_dir.name, xuid, scid, entry))
    return saves


def game_names(packages) -> Dict[str, str]:
    """Names for packages: from games.json, else the name Windows has for the installed app."""
    names = {pkg: entry.name for pkg, entry in load_catalog().items()}
    unknown = set(packages) - set(names)
    return {**installed_display_names(unknown), **names}


def discover(packages_root: Path, game: str | None = None, user: int | None = None) -> Tuple[Dict[str, str], List[UserSave]]:
    """Saves matching the --game and --user filters, and names for their games."""
    saves = find_saves(packages_root, user)
    names = game_names({s.package for s in saves})
    if game is not None:
        saves = [s for s in saves if game_matches(game, s.package, names)]
    return names, saves
