"""Converting Xbox saves into the files the Steam/Epic version of a game uses.

Derived from XGP-save-extractor (https://github.com/Z1ni/XGP-save-extractor), MIT License,
Copyright (c) 2021 Mark Mäkinen. Thanks to @snoozbuster for figuring out the container format at
https://github.com/goatfungus/NMSSaveEditor/issues/306.

Each game in games.json names a handler, which turns the game's save containers into a list of
(name in the ZIP, file with the data) pairs.
"""

import gzip
import json
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Tuple

from gss import GssError
from gss.discovery import UserSave
from gss.fsutil import slugify, unique_path
from gss.games import CatalogEntry
from gss.wgs import SaveContainer, read_saves

OutputFiles = List[Tuple[str, Path]]
Handler = Callable[[List[SaveContainer], Dict[str, Any], Path], OutputFiles]
HANDLERS: Dict[str, Handler] = {}


def handler(name: str):
    def register(func: Handler) -> Handler:
        HANDLERS[name] = func
        return func

    return register


def _first_file(container: SaveContainer) -> Path:
    if not container.files:
        raise GssError(f'Save "{container.name}" has no files')
    return container.files[0].path


@handler("1c1f")
def one_container_one_file(containers, args, tmp):
    """Each container holds one file, named after the container."""
    suffix = args.get("suffix") or ""
    return [(c.name + suffix, _first_file(c)) for c in containers]


@handler("1cnf")
def one_container_many_files(containers, args, tmp):
    """A single container holds all the save files."""
    suffix = args.get("suffix") or ""
    if not containers:
        return []
    return [(f.name + suffix, f.path) for f in containers[0].files]


@handler("1cnf-folder")
def container_per_folder(containers, args, tmp):
    """Each container is a folder of files."""
    return [(f"{c.name}/{f.name}", f.path) for c in containers for f in c.files]


@handler("control")
def control(containers, args, tmp):
    """Each container is a folder; files get a .chunk extension plus a --containerDisplayName.chunk."""
    out = []
    for c in containers:
        display_name = tmp / f"display_name_{len(out)}.chunk"
        display_name.write_text(c.name)
        out.append((f"{c.name}/--containerDisplayName.chunk", display_name))
        out += [(f"{c.name}/{f.name}.chunk", f.path) for f in c.files]
    return out


@handler("starfield")
def starfield(containers, args, tmp):
    """Each container under Saves/ is one save, split into parts that are joined into an .sfs file.

    Old format: BETHESDAPFH header plus P0P, P1P, ... parts, each padded to 16 bytes with
    "padding\\0". New format (1.9.51+): a toc plus BlobData0, BlobData1, ... already padded."""
    folder = tmp / "Starfield"
    folder.mkdir()
    padding = ("padding\0" * 2).encode("ascii")
    out = []
    for c in containers:
        path = PurePosixPath(c.name)
        # Skip non-save containers, e.g. ones under Settings/
        if path.parent.name != "Saves":
            continue
        new_format = any(f.name == "toc" for f in c.files)
        parts = {}
        for f in c.files:
            if f.name == "toc":
                continue
            if new_format:
                idx = int(f.name.removeprefix("BlobData"))
            else:
                idx = 0 if f.name == "BETHESDAPFH" else int(f.name.strip("P")) + 1
            parts[idx] = f.path
        sfs = folder / path.name
        with sfs.open("wb") as out_f:
            for _, part in sorted(parts.items()):
                size = out_f.write(part.read_bytes())
                pad = 16 - size % 16
                if pad != 16:
                    out_f.write(padding[:pad])
        out.append((path.name, sfs))
    return out


@handler("lies-of-p")
def lies_of_p(containers, args, tmp):
    """Container names start with a numeric ID to drop; files need a .sav suffix."""
    out = []
    for c in containers:
        # A name that is all digits is kept whole, as the original extractor did
        name = c.name.lstrip("0123456789") or c.name
        out.append((name + ".sav", _first_file(c)))
    return out


@handler("palworld")
def palworld(containers, args, tmp):
    """Each "-" in a container name is a folder separator; files need a .sav suffix."""
    return [(c.name.replace("-", "/") + ".sav", _first_file(c)) for c in containers]


@handler("like-a-dragon")
def like_a_dragon(containers, args, tmp):
    """data files keep the container path (datasav -> data.sav, datasys -> data.sys); icons are optional."""
    icon_format = args.get("icon_format")
    out = []
    for c in containers:
        path = PurePosixPath(c.name)
        if path.name == "datasav":
            path = path.with_name("data.sav")
        elif path.name == "datasys":
            path = path.with_name("data.sys")
        for f in c.files:
            if f.name.lower() == "data":
                out.append((str(path), f.path))
            elif f.name.lower() == "icon" and icon_format is not None:
                out.append((str(path.with_name(f"{path.parent.name}_icon.{icon_format}")), f.path))
    return out


@handler("cricket-24")
def cricket_24(containers, args, tmp):
    """Like 1cnf-folder, with .CHUNK0 removed from file names and .SAV added."""
    out = []
    for c in containers:
        for f in c.files:
            name = f.name.removesuffix(".CHUNK0")
            if "CHUNK" in name:
                raise GssError(f"Unexpected chunk name {f.name!r}, please report it")
            out.append((f"{c.name}/{name}.SAV", f.path))
    return out


@handler("forza")
def forza(containers, args, tmp):
    """Files are named <container>.<file>."""
    return [(f"{c.name}.{f.name}", f.path) for c in containers for f in c.files]


@handler("arcade-paradise")
def arcade_paradise(containers, args, tmp):
    """One container with one file, named RATSaveData.dat on Steam."""
    if not containers:
        return []
    return [("RATSaveData.dat", _first_file(containers[0]))]


@handler("state-of-decay-2")
def state_of_decay_2(containers, args, tmp):
    """Like 1cnf, without the folder part of the file names, plus a .sav suffix."""
    if not containers:
        return []
    return [(f.name.split("/")[-1] + ".sav", f.path) for f in containers[0].files]


@handler("railway-empire-2")
def railway_empire_2(containers, args, tmp):
    """Each container is one save: its "savegame" file, named after the container."""
    return [(c.name, f.path) for c in containers for f in c.files if f.name == "savegame"]


@handler("coral-island")
def coral_island(containers, args, tmp):
    """1c1f with .sav; files starting with "Backup" go in a Backup/ folder without that prefix."""
    out = []
    for c in containers:
        name = c.name + ".sav"
        if name.startswith("Backup"):
            name = "Backup/" + name.removeprefix("Backup")
        out.append((name, _first_file(c)))
    return out


@handler("one-lonely-outpost")
def one_lonely_outpost(containers, args, tmp):
    """One gzipped JSON file holding every file of the Steam version."""
    if not containers:
        return []
    folder = tmp / "OneLonelyOutpost"
    folder.mkdir()
    data = json.loads(gzip.decompress(_first_file(containers[0]).read_bytes()))
    out = []
    for entry in data["files"]["$values"]:
        name = entry["name"].removeprefix("ConsoleSaves/")
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        # Text mode like the original extractor, which is confirmed to work with the Steam version
        with path.open("w") as f:
            f.write(entry["datas"]["$values"][0])
        out.append((name, path))
    return out


def convert(containers: List[SaveContainer], entry: CatalogEntry, tmp: Path) -> OutputFiles:
    try:
        func = HANDLERS[entry.handler]
    except KeyError:
        raise GssError(f'Unknown handler "{entry.handler}" for {entry.name} in games.json') from None
    return func(containers, entry.handler_args, tmp)


@dataclass
class Extracted:
    path: Path
    files: List[str]


def extract_save(save: UserSave, entry: CatalogEntry, out_dir: Path) -> Extracted | None:
    """Write a ZIP with one account's saves for one game, converted for Steam/Epic.

    Returns None if there was nothing to extract."""
    containers = read_saves(save.path)
    with tempfile.TemporaryDirectory(prefix="gss-extract-", ignore_cleanup_errors=True) as tmp:
        files = convert(containers, entry, Path(tmp))
        if not files:
            return None
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        zip_path = unique_path(out_dir / f"{slugify(entry.name)}_{save.xuid}_{stamp}.zip")
        with zipfile.ZipFile(zip_path, "x", zipfile.ZIP_DEFLATED) as zf:
            for name, path in files:
                zf.write(path, arcname=name)
    return Extracted(zip_path, [name for name, _ in files])
