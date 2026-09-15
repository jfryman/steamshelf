from steamshelf import engine
from steamshelf.collections import Collection, CollectionSet
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
    config.enabled["deck"] = False
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
