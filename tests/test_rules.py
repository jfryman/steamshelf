from steamshelf.hltb import HltbResult
from steamshelf.rules import RuleConfig, categories_for, flatten, hltb_bucket
from steamshelf.steamapi import AppMetadata


def portal2() -> AppMetadata:
    return AppMetadata(
        appid=620, name="Portal 2", app_type="game", windows=True, linux=True,
        deck="Verified", review_desc="Overwhelmingly Positive", review_count=466748,
        release_year=2011,
    )


def test_default_names_match_depressurizer():
    names = flatten(categories_for(portal2(), HltbResult(1, "Portal 2", main_hours=8.6), RuleConfig()))
    assert names == {
        "(HLTB)  5-10",
        "(Platform) Windows",
        "(Platform) Linux",
        "(Score) Overwhelmingly Positive",
        "(Deck) Verified",
        "(Year) 2011",
    }


def test_missing_hltb_data_becomes_unknown():
    grouped = categories_for(portal2(), None, RuleConfig())
    assert grouped["hltb"] == ["(HLTB) Unknown"]


def test_thinly_reviewed_games_are_unrated():
    meta = portal2()
    meta.review_count = 3
    grouped = categories_for(meta, None, RuleConfig())
    assert grouped["rating"] == ["(Score) Unrated"]


def test_untested_deck_status_gets_its_own_bucket():
    # Not skipped: a family with no bucket for "no answer" never settles, so the
    # game is re-examined on every run. See test_every_family_always_answers.
    meta = portal2()
    meta.deck = "Unknown"
    assert categories_for(meta, None, RuleConfig())["deck"] == ["(Deck) Unknown"]


def test_undatable_game_gets_a_year_bucket():
    meta = portal2()
    meta.release_year = 0
    assert categories_for(meta, None, RuleConfig())["year"] == ["(Year) Unknown"]


def test_every_family_always_answers():
    """No metadata at all must still put the game in one collection per family."""
    config = RuleConfig()
    blank = AppMetadata(appid=1, app_type="game")
    grouped = categories_for(blank, None, config)
    for family in config.active_families():
        if family == "platform":
            continue  # an app with no store page genuinely runs nowhere
        assert grouped[family], f"{family} produced no collection"


def test_deck_skip_restores_the_old_behaviour():
    config = RuleConfig(deck_skip=("Unknown",))
    meta = portal2()
    meta.deck = "Unknown"
    assert categories_for(meta, None, config)["deck"] == []


def test_a_bare_year_collection_from_another_tool_is_not_ours():
    config = RuleConfig()
    # Depressurizer's "could not date it" bucket. The family prefix carries a
    # trailing space, so a bare "(Year)" is not even recognised as ours -- it is
    # neither read as filing nor ever written to.
    assert not config.owns("(Year)")
    assert not config.can_produce("(Year)")
    assert config.can_produce("(Year) 2013")
    assert config.can_produce("(Year) Unknown")


def test_buckets_are_half_open():
    config = RuleConfig()
    assert hltb_bucket(4.9, config) == " 0-5"
    assert hltb_bucket(5.0, config) == " 5-10"
    assert hltb_bucket(9999, config) == "50+"


def test_foreign_collections_in_a_managed_family_are_not_writable():
    config = RuleConfig()
    # Left behind by Depressurizer; steamshelf reads it but must never empty it.
    assert config.owns("(Platform) SteamOS")
    assert not config.can_produce("(Platform) SteamOS")
    assert config.can_produce("(Platform) Linux")
    assert not config.owns("Favorites")


def test_year_prefers_the_original_release_over_the_steam_listing():
    meta = portal2()
    meta.release_year = 2009  # when LucasArts put it on Steam
    hltb = HltbResult(1, "Indiana Jones and the Last Crusade", main_hours=4.0, release_year=1989)
    assert categories_for(meta, hltb, RuleConfig())["year"] == ["(Year) 1989"]


def test_year_falls_back_to_the_store_date_without_an_hltb_match():
    meta = portal2()
    meta.release_year = 2011
    assert categories_for(meta, None, RuleConfig())["year"] == ["(Year) 2011"]
