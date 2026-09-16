"""Working out which games need filing, and what that means for collections."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from . import rules
from .collections import Collection, CollectionSet
from .hltb import HltbClient, HltbError, HltbResult
from .rules import RuleConfig
from .steamapi import AppMetadata, OwnedGame, SteamClient

# App types that are not games and should never be filed into a play-time bucket.
SKIP_TYPES = {"dlc", "demo", "music", "video", "episode", "hardware", "mod", "series"}


@dataclass
class GamePlan:
    game: OwnedGame
    meta: AppMetadata
    hltb: HltbResult | None
    desired: dict[str, list[str]]
    current: set[str]

    @property
    def desired_names(self) -> set[str]:
        return rules.flatten(self.desired)

    @property
    def additions(self) -> set[str]:
        return self.desired_names - self.current

    def removals(self, config: RuleConfig) -> set[str]:
        """Managed collections this game should no longer be in."""
        stale = set()
        for name in self.current - self.desired_names:
            family = config.family_of(name)
            # Only pull a game out of a family we are actively rewriting, and
            # only from a collection this config would itself have created.
            if family and self.desired.get(family) is not None and config.can_produce(name):
                stale.add(name)
        return stale

    def is_changed(self, config: RuleConfig) -> bool:
        # Membership of a collection we may not write -- "(Platform) SteamOS",
        # say -- is not a pending change, so removals() is the honest test.
        return bool(self.additions or self.removals(config))


@dataclass
class Plan:
    games: list[GamePlan] = field(default_factory=list)
    skipped: list[tuple[OwnedGame, str]] = field(default_factory=list)
    retry_later: list[tuple[OwnedGame, str]] = field(default_factory=list)

    def changes(self, config: RuleConfig) -> list[GamePlan]:
        return [g for g in self.games if g.is_changed(config)]

    def collection_deltas(self, config: RuleConfig) -> dict[str, tuple[set[int], set[int]]]:
        """collection name -> (appids to add, appids to remove)."""
        deltas: dict[str, tuple[set[int], set[int]]] = {}
        for plan in self.games:
            for name in plan.additions:
                deltas.setdefault(name, (set(), set()))[0].add(plan.game.appid)
            for name in plan.removals(config):
                deltas.setdefault(name, (set(), set()))[1].add(plan.game.appid)
        return deltas


def managed_membership(
    collection_set: CollectionSet, config: RuleConfig
) -> dict[int, set[str]]:
    """appid -> names of steamshelf-managed collections it currently belongs to."""
    result: dict[int, set[str]] = {}
    for collection in collection_set.live():
        if not config.owns(collection.name):
            continue
        for appid in collection.added:
            result.setdefault(appid, set()).add(collection.name)
    return result


def needs_filing(
    appid: int, membership: dict[int, set[str]], config: RuleConfig
) -> bool:
    """True when any enabled family has no collection holding this game yet."""
    current = membership.get(appid, set())
    seen = {config.family_of(name) for name in current}
    return any(family not in seen for family in config.active_families())


def select_targets(
    owned: Iterable[OwnedGame],
    collection_set: CollectionSet,
    config: RuleConfig,
    *,
    force_all: bool = False,
) -> tuple[list[OwnedGame], dict[int, set[str]]]:
    membership = managed_membership(collection_set, config)
    if force_all:
        return list(owned), membership
    return [g for g in owned if needs_filing(g.appid, membership, config)], membership


def build_plan(
    targets: list[OwnedGame],
    membership: dict[int, set[str]],
    steam: SteamClient,
    hltb: HltbClient,
    config: RuleConfig,
    *,
    progress: Callable[[int, int, OwnedGame], None] | None = None,
) -> Plan:
    plan = Plan()
    want_deck = config.enabled.get(rules.DECK, False)
    want_hltb = config.enabled.get(rules.HLTB, False)

    for index, game in enumerate(targets, start=1):
        if progress:
            progress(index, len(targets), game)

        try:
            meta = steam.metadata(game.appid, game.name, want_deck=want_deck)
        except Exception as exc:  # noqa: BLE001 - a whole library sweep is too
            # expensive to throw away because one app's lookup went wrong.
            plan.retry_later.append((game, f"Steam lookup failed: {exc}"))
            continue

        if meta.app_type in SKIP_TYPES:
            plan.skipped.append((game, f"not a game ({meta.app_type})"))
            continue
        if not meta.app_type and not meta.platforms:
            # Delisted or region-locked apps come back empty from the storefront.
            plan.skipped.append((game, "no store page"))
            continue

        result = None
        hltb_failed = False
        if want_hltb:
            try:
                result = hltb.lookup(game.appid, meta.name or game.name)
            except (HltbError, OSError, TimeoutError):
                hltb_failed = True

        desired = rules.categories_for(meta, result, config)
        if hltb_failed:
            # Leaving the family out means no additions and no removals for it,
            # so the game keeps its current bucket and is picked up again later.
            desired.pop(rules.HLTB, None)
            plan.retry_later.append((game, "HowLongToBeat lookup failed"))

        plan.games.append(
            GamePlan(
                game=game,
                meta=meta,
                hltb=result,
                desired=desired,
                current=membership.get(game.appid, set()),
            )
        )
    return plan


def apply_plan(
    plan: Plan, collection_set: CollectionSet, config: RuleConfig
) -> list[Collection]:
    """Mutate the collection set in place; returns the collections that changed."""
    touched: dict[str, Collection] = {}
    for name, (add, remove) in plan.collection_deltas(config).items():
        collection = collection_set.ensure(name)
        appids = set(collection.added)
        appids |= add
        appids -= remove
        if appids != set(collection.added):
            collection.added = sorted(appids)
            touched[collection.id] = collection
    return list(touched.values())
