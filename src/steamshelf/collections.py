"""Steam library collections, as stored in cloud config namespace 1.

Each collection is one entry keyed ``user-collections.<id>`` whose value is a
JSON blob::

    {"id": "uc-AbCdEf", "name": "Shooters", "added": [220, 620], "removed": []}

Collections built from a filter carry a ``filterSpec`` instead of a hand-picked
``added`` list; steamshelf leaves those alone, since Steam recomputes them.
``favorite`` and ``hidden`` are built-in and are also left alone.
"""

from __future__ import annotations

import json
import random
import string
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

NAMESPACE_USER = 1
KEY_PREFIX = "user-collections."
BUILTIN_IDS = {"favorite", "hidden"}

_ID_ALPHABET = string.ascii_letters + string.digits


def new_collection_id() -> str:
    return "uc-" + "".join(random.choices(_ID_ALPHABET, k=12))


@dataclass
class Collection:
    id: str
    name: str
    added: list[int] = field(default_factory=list)
    removed: list[int] = field(default_factory=list)
    filter_spec: Any = None
    entry_version: int = 0
    is_deleted: bool = False

    @property
    def key(self) -> str:
        return KEY_PREFIX + self.id

    @property
    def is_dynamic(self) -> bool:
        return self.filter_spec is not None

    @property
    def is_builtin(self) -> bool:
        return self.id in BUILTIN_IDS

    @property
    def editable(self) -> bool:
        return not self.is_deleted and not self.is_dynamic and not self.is_builtin

    def to_value(self) -> str:
        payload: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "added": sorted(set(self.added)),
            "removed": sorted(set(self.removed)),
        }
        if self.filter_spec is not None:
            payload["filterSpec"] = self.filter_spec
        return json.dumps(payload, separators=(",", ":"))

    def to_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {"key": self.key, "timestamp": int(time.time())}
        if self.is_deleted:
            entry["is_deleted"] = True
        else:
            entry["value"] = self.to_value()
        return entry


def parse_entry(entry: dict[str, Any]) -> Collection | None:
    key = entry.get("key", "")
    if not key.startswith(KEY_PREFIX):
        return None
    collection_id = key[len(KEY_PREFIX) :]
    if entry.get("is_deleted") or not entry.get("value"):
        return Collection(id=collection_id, name="", is_deleted=True,
                          entry_version=int(entry.get("version", 0) or 0))
    try:
        value = json.loads(entry["value"])
    except json.JSONDecodeError:
        return None
    return Collection(
        id=value.get("id", collection_id),
        name=value.get("name", ""),
        added=[int(a) for a in value.get("added", [])],
        removed=[int(a) for a in value.get("removed", [])],
        filter_spec=value.get("filterSpec"),
        entry_version=int(entry.get("version", 0) or 0),
    )


@dataclass
class CollectionSet:
    """All of a user's collections, plus the namespace version they came from."""

    namespace_version: int = 0
    collections: dict[str, Collection] = field(default_factory=dict)

    @classmethod
    def from_entries(cls, entries: Iterable[dict[str, Any]], namespace_version: int = 0) -> CollectionSet:
        found: dict[str, Collection] = {}
        for entry in entries:
            collection = parse_entry(entry)
            if collection is not None:
                found[collection.id] = collection
        return cls(namespace_version=namespace_version, collections=found)

    def live(self) -> list[Collection]:
        return [c for c in self.collections.values() if not c.is_deleted]

    def editable(self) -> list[Collection]:
        return [c for c in self.collections.values() if c.editable]

    def by_name(self, name: str) -> Collection | None:
        for collection in self.live():
            if collection.name == name:
                return collection
        return None

    def membership(self, *, ignore_names: set[str] | None = None) -> dict[int, set[str]]:
        """appid -> names of the hand-curated collections it belongs to."""
        ignore = ignore_names or set()
        result: dict[int, set[str]] = {}
        for collection in self.live():
            if collection.is_builtin or collection.name in ignore:
                continue
            # A dynamic collection still tells us the game is filed somewhere,
            # but only its explicit `added` list is knowable without Steam's
            # filter engine.
            for appid in collection.added:
                result.setdefault(appid, set()).add(collection.name)
        return result

    def uncategorized(self, appids: Iterable[int], *, ignore_names: set[str] | None = None) -> list[int]:
        member = self.membership(ignore_names=ignore_names)
        return [appid for appid in appids if appid not in member]

    def ensure(self, name: str) -> Collection:
        existing = self.by_name(name)
        if existing is not None:
            return existing
        collection = Collection(id=new_collection_id(), name=name)
        self.collections[collection.id] = collection
        return collection
