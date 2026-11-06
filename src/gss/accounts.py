"""Xbox account IDs (XUIDs) and the save folder names built from them."""

import json
import re
from pathlib import Path
from typing import Tuple

XBOX_APP_PACKAGE = "Microsoft.XboxApp_8wekyb3d8bbwe"


def parse_xuid(text: str) -> int:
    """Read a XUID written in decimal (2535412345678901) or hex (0x000901F1B0392C35, 000901F1B0392C35).

    Raises ValueError if it isn't one."""
    t = text.strip()
    try:
        if t.lower().startswith("0x"):
            value = int(t[2:], 16)
        elif re.search(r"[a-fA-F]", t) or (len(t) == 16 and t.startswith("000")):
            # Hex as used in save folder names: 16 digits, usually starting with 0009
            value = int(t, 16)
        else:
            value = int(t, 10)
    except ValueError:
        raise ValueError(f"not a valid Xbox account ID (XUID): {text!r}") from None
    if not 0 < value < 2**64:
        raise ValueError(f"Xbox account ID (XUID) out of range: {text!r}")
    return value


def user_dir_name(xuid: int, scid: str) -> str:
    """The save folder name for an account: <XUID as 16 hex digits>_<SCID>."""
    return f"{xuid:016X}_{scid}"


def split_user_dir_name(name: str) -> Tuple[int, str] | None:
    """(xuid, scid) from a save folder name, or None if it isn't one."""
    parts = name.split("_")
    if len(parts) != 2 or len(parts[0]) != 16:
        return None
    try:
        xuid = int(parts[0], 16)
        int(parts[1], 16)
    except ValueError:
        return None
    return xuid, parts[1]


def gamertag(xuid: int, packages_root: Path) -> str | None:
    """The gamertag of the account signed in to the Xbox app, if that's this XUID."""
    try:
        path = packages_root / XBOX_APP_PACKAGE / "LocalState" / "XboxLiveGamer.xml"
        with path.open("r", encoding="utf-8") as f:
            gamer = json.load(f)
        if gamer.get("XboxUserId") != xuid:
            return None
        return gamer.get("Gamertag")
    except (OSError, ValueError, AttributeError):
        return None
