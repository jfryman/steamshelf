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
    }


def test_missing_hltb_data_becomes_unknown():
    grouped = categories_for(portal2(), None, RuleConfig())
    assert grouped["hltb"] == ["(HLTB) Unknown"]


def test_thinly_reviewed_games_are_unrated():
    meta = portal2()
    meta.review_count = 3
    grouped = categories_for(meta, None, RuleConfig())
    assert grouped["rating"] == ["(Score) Unrated"]


def test_untested_deck_status_is_skipped():
    meta = portal2()
    meta.deck = "Unknown"
    assert categories_for(meta, None, RuleConfig())["deck"] == []


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
