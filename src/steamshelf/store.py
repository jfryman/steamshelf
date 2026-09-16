"""Reading and writing the collection store.

The authoritative copy lives in Steam's cloud, reachable only over a CM
connection (:mod:`steamshelf.cm`).  The running client also keeps a mirror at
``userdata/<id>/config/cloudstorage/cloud-storage-namespace-1.json``, which is
handy for inspecting things without logging in.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from . import cm
from .collections import NAMESPACE_USER, Collection, CollectionSet

STEAM_DIRS = [
    Path.home() / ".local/share/Steam",
    Path.home() / ".steam/steam",
    Path.home() / ".var/app/com.valvesoftware.Steam/data/Steam",
    Path.home() / "Library/Application Support/Steam",
]


class StoreError(RuntimeError):
    pass


# -- local mirror ------------------------------------------------------------


def local_namespace_path(steamid3: int) -> Path | None:
    for base in STEAM_DIRS:
        candidate = base / "userdata" / str(steamid3) / "config/cloudstorage" / (
            f"cloud-storage-namespace-{NAMESPACE_USER}.json"
        )
        if candidate.exists():
            return candidate
    return None


def read_local(steamid3: int) -> CollectionSet:
    path = local_namespace_path(steamid3)
    if path is None:
        raise StoreError(
            f"no local Steam collection mirror found for account {steamid3}; "
            "is Steam installed for this user?"
        )
    raw = json.loads(path.read_text())
    entries = [entry for _key, entry in raw]
    version = 0
    namespaces = path.with_name("cloud-storage-namespaces.json")
    if namespaces.exists():
        for ns_id, ns_version in json.loads(namespaces.read_text()):
            if int(ns_id) == NAMESPACE_USER:
                version = int(ns_version)
    return CollectionSet.from_entries(entries, namespace_version=version)


def _steam_config_dir(steamid3: int) -> Path | None:
    for base in STEAM_DIRS:
        candidate = base / "userdata" / str(steamid3) / "config"
        if candidate.is_dir():
            return candidate
    return None


def _apps_block(text: str) -> str:
    """The body of Software/Valve/Steam/apps in a text VDF, brace-matched."""
    marker = text.find('"apps"')
    if marker < 0:
        return ""
    start = text.find("{", marker)
    if start < 0:
        return ""
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def client_known_appids(steamid3: int) -> set[int]:
    """Appids the installed Steam client tracks state for.

    `IPlayerService/GetOwnedGames` reports only apps the account actually owns,
    which leaves out two kinds of thing the library still shows: titles shared
    from another account via Family Sharing, and free-to-play apps that have
    never been launched.  The client records both in `localconfig.vdf`, so this
    is the practical way to reach them.  Returns everything found; callers rely
    on the usual store-page checks to discard tools and runtimes.
    """
    config = _steam_config_dir(steamid3)
    if config is None:
        return set()
    local = config / "localconfig.vdf"
    if not local.exists():
        return set()
    block = _apps_block(local.read_text(errors="replace"))
    return {int(m.group(1)) for m in re.finditer(r'^\t*"(\d{1,8})"\s*$', block, re.M)}


def steam_is_running() -> bool:
    for pid in os.listdir("/proc") if Path("/proc").is_dir() else []:
        if not pid.isdigit():
            continue
        try:
            cmdline = Path("/proc", pid, "cmdline").read_bytes()
        except OSError:
            continue
        if b"/Steam/ubuntu12_32/steam\x00" in cmdline or cmdline.split(b"\x00")[0].endswith(b"/steam"):
            return True
    return False


def write_snapshot(data: dict[str, Any], path: Path) -> Path:
    """Save a raw namespace dump so a bad run can be undone by hand."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1))
    return path


def snapshot_path(steamid: int) -> Path:
    from .session import CACHE_DIR  # noqa: PLC0415 - avoids an import cycle

    stamp = time.strftime("%Y%m%d-%H%M%S")
    return CACHE_DIR / "backups" / f"collections-{steamid}-{stamp}.json"


# -- cloud -------------------------------------------------------------------


class CloudStore:
    """Downloads and uploads collections over an authenticated CM connection."""

    def __init__(self, client: cm.CMClient):
        self.client = client

    @classmethod
    def connect(cls, account_name: str, refresh_token: str, steamid: int) -> CloudStore:
        client = cm.CMClient()
        client.connect()
        client.logon(account_name, refresh_token, steamid)
        return cls(client)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> CloudStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def read_raw(self) -> dict[str, Any]:
        """The namespace exactly as Steam sends it -- what `backup` writes out."""
        return self.client.download_namespace(NAMESPACE_USER, 0)

    def read(self) -> CollectionSet:
        data = self.read_raw()
        return CollectionSet.from_entries(
            data.get("entries", []), namespace_version=int(data.get("version", 0))
        )

    def write(self, collections: list[Collection], namespace_version: int) -> int:
        entries: list[dict[str, Any]] = [c.to_entry() for c in collections]
        if not entries:
            return namespace_version
        return self.client.upload_entries(
            entries, enamespace=NAMESPACE_USER, version=namespace_version
        )
