from steamshelf import engine
from steamshelf.collections import Collection, CollectionSet
from steamshelf.hltb import HltbError
from steamshelf.rules import RuleConfig
from steamshelf.steamapi import AppMetadata, OwnedGame


def collection_set(*collections: Collection) -> CollectionSet:
    return CollectionSet(namespace_version=1, collections={c.id: c for c in collections})


def test_a_game_missing_one_family_needs_filing():
    config = RuleConfig()
    cs = collection_set(Collection(id="uc-1", name="(HLTB) 10-20", added=[620]))
    membership = engine.managed_membership(cs, config)
    assert engine.needs_filing(620, membership, config)  # no platform/score/deck yet


def test_a_fully_filed_game_is_left_alone():
    config = RuleConfig()
    config.enabled.update({"deck": False, "year": False})
    cs = collection_set(
        Collection(id="uc-1", name="(HLTB) 10-20", added=[620]),
        Collection(id="uc-2", name="(Platform) Windows", added=[620]),
        Collection(id="uc-3", name="(Score) Mixed", added=[620]),
    )
    membership = engine.managed_membership(cs, config)
    assert not engine.needs_filing(620, membership, config)


def test_built_in_collections_do_not_count_as_filing():
    config = RuleConfig()
    cs = collection_set(Collection(id="favorite", name="Favorites", added=[620]))
    membership = engine.managed_membership(cs, config)
    assert membership == {}


def test_plan_moves_a_game_between_buckets():
    config = RuleConfig()
    config.enabled.update({"platform": False, "rating": False, "deck": False})
    plan = engine.Plan(games=[
        engine.GamePlan(
            game=OwnedGame(appid=620, name="Portal 2"),
            meta=AppMetadata(appid=620, app_type="game"),
            hltb=None,
            desired={"hltb": ["(HLTB) 10-20"]},
            current={"(HLTB)  5-10"},
        )
    ])
    assert plan.collection_deltas(config) == {
        "(HLTB) 10-20": ({620}, set()),
        "(HLTB)  5-10": (set(), {620}),
    }


def test_apply_plan_only_touches_affected_collections():
    config = RuleConfig()
    config.enabled.update({"platform": False, "rating": False, "deck": False})
    untouched = Collection(id="uc-keep", name="Roguelikes", added=[1, 2])
    cs = collection_set(untouched, Collection(id="uc-1", name="(HLTB)  5-10", added=[620, 70]))
    plan = engine.Plan(games=[
        engine.GamePlan(
            game=OwnedGame(appid=620, name="Portal 2"),
            meta=AppMetadata(appid=620, app_type="game"),
            hltb=None,
            desired={"hltb": ["(HLTB) 10-20"]},
            current={"(HLTB)  5-10"},
        )
    ])
    touched = engine.apply_plan(plan, cs, config)
    assert {c.name for c in touched} == {"(HLTB) 10-20", "(HLTB)  5-10"}
    assert cs.by_name("(HLTB)  5-10").added == [70]
    assert cs.by_name("(HLTB) 10-20").added == [620]
    assert untouched.added == [1, 2]


class _BoomSteam:
    """A storefront client that fails for one app and works for the rest."""

    def __init__(self, bad_appid: int):
        self.bad_appid = bad_appid

    def metadata(self, appid, name="", *, want_deck=True):
        if appid == self.bad_appid:
            raise TimeoutError("the read operation timed out")
        return AppMetadata(appid=appid, name=name, app_type="game", windows=True)


class _NoHltb:
    def lookup(self, appid, title):
        return None


def test_one_failed_lookup_does_not_end_the_sweep():
    config = RuleConfig()
    config.enabled.update({"hltb": False, "rating": False, "deck": False})
    games = [OwnedGame(appid=i, name=f"Game {i}") for i in (70, 220, 620)]

    plan = engine.build_plan(games, {}, _BoomSteam(220), _NoHltb(), config)

    assert [p.game.appid for p in plan.games] == [70, 620]
    assert [g.appid for g, _reason in plan.retry_later] == [220]


def test_membership_of_a_foreign_collection_is_not_a_pending_change():
    config = RuleConfig()
    config.enabled.update({"hltb": False, "rating": False, "deck": False})
    item = engine.GamePlan(
        game=OwnedGame(appid=620, name="Portal 2"),
        meta=AppMetadata(appid=620, app_type="game"),
        hltb=None,
        desired={"platform": ["(Platform) Windows"]},
        # Left by Depressurizer; we may not write it, so it is not a change.
        current={"(Platform) Windows", "(Platform) SteamOS"},
    )
    assert item.removals(config) == set()
    assert not item.is_changed(config)


def test_an_unknown_answer_still_settles():
    """A family that answers "unknown" files a collection, so the game settles.

    Without this, needs_filing() flags the game on every run forever.
    """
    config = RuleConfig()
    cs = collection_set(
        Collection(id="uc-1", name="(HLTB) Unknown", added=[620]),
        Collection(id="uc-2", name="(Platform) Windows", added=[620]),
        Collection(id="uc-3", name="(Score) Unrated", added=[620]),
        Collection(id="uc-4", name="(Deck) Unknown", added=[620]),
        Collection(id="uc-5", name="(Year) Unknown", added=[620]),
    )
    assert not engine.needs_filing(620, engine.managed_membership(cs, config), config)


class _FlakyHltb:
    def lookup(self, appid, title):
        raise HltbError("session expired or invalid fingerprint")


def test_a_failed_hltb_lookup_defers_year_too():
    """Steam's listing date is not a safe fallback when HLTB merely failed."""
    config = RuleConfig()
    games = [OwnedGame(appid=620, name="Portal 2")]
    plan = engine.build_plan(games, {}, _BoomSteam(0), _FlakyHltb(), config)

    assert len(plan.games) == 1
    desired = plan.games[0].desired
    assert "hltb" not in desired and "year" not in desired
    assert [g.appid for g, _r in plan.retry_later] == [620]
