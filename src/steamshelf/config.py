"""User configuration (``~/.config/steamshelf/config.toml``)."""

from __future__ import annotations

import tomllib
from pathlib import Path

from . import rules
from .rules import DEFAULT_HLTB_BUCKETS, DEFAULT_NAME_FORMAT, RuleConfig
from .session import CONFIG_PATH

DEFAULT_TOML = '''# steamshelf configuration
# Every key is optional; delete this file to go back to these defaults.

[onepassword]
# Item name, UUID, or op:// reference holding your Steam login.
item = "Steam"
# vault = "Private"

[categories]
# How collection names are built. The defaults match Depressurizer's AutoCat
# naming, so steamshelf files games into collections you may already have.
name_format = "({prefix}) {value}"

[categories.enable]
# Category families to apply.
hltb = true
platform = true
rating = true
deck = true
year = true

[categories.prefixes]
hltb = "HLTB"
platform = "Platform"
rating = "Score"
deck = "Deck"
year = "Year"

[categories.hltb]
# Which HowLongToBeat figure to bucket on:
#   main | main_extra | completionist | all
style = "main"
unknown = "Unknown"
# Upper bound in hours -> label. The last entry catches everything above it.
buckets = [
    [5, " 0-5"],
    [10, " 5-10"],
    [20, "10-20"],
    [50, "20-50"],
    [100000, "50+"],
]

[categories.rating]
# Steam scores computed from fewer reviews than this are filed as "Unrated".
min_reviews = 25
unrated = "Unrated"

[categories.deck]
# Valve reports "Unknown" for anything it has not tested on a Steam Deck.
# Every family needs a bucket for "no answer", or games missing one are
# re-examined on every run instead of settling.
unknown = "Unknown"
# Deck states to file nothing for, e.g. ["Unknown"] to leave untested games out.
skip = []

[categories.year]
# Games whose store page has no usable release date.
unknown = "Unknown"
'''


class Config:
    def __init__(self, data: dict | None = None):
        self.data = data or {}

    @property
    def op_item(self) -> str:
        return self.data.get("onepassword", {}).get("item", "Steam")

    @property
    def op_vault(self) -> str | None:
        return self.data.get("onepassword", {}).get("vault")

    def rules(self) -> RuleConfig:
        section = self.data.get("categories", {})
        base = RuleConfig()

        def table(name: str) -> dict:
            value = section.get(name)
            return value if isinstance(value, dict) else {}

        hltb, rating = table("hltb"), table("rating")
        deck, year = table("deck"), table("year")
        prefixes = dict(base.prefixes)
        prefixes.update(section.get("prefixes", {}))

        enabled = dict(base.enabled)
        for family, value in section.get("enable", {}).items():
            if family in rules.FAMILIES and isinstance(value, bool):
                enabled[family] = value

        buckets = hltb.get("buckets")
        parsed = (
            [(float(upper), str(label)) for upper, label in buckets]
            if buckets
            else list(DEFAULT_HLTB_BUCKETS)
        )

        return RuleConfig(
            name_format=section.get("name_format", DEFAULT_NAME_FORMAT),
            prefixes=prefixes,
            enabled=enabled,
            hltb_style=hltb.get("style", base.hltb_style),
            hltb_buckets=parsed,
            hltb_unknown=hltb.get("unknown", base.hltb_unknown),
            min_reviews=int(rating.get("min_reviews", base.min_reviews)),
            rating_unrated=rating.get("unrated", base.rating_unrated),
            deck_unknown=deck.get("unknown", base.deck_unknown),
            deck_skip=tuple(deck.get("skip", base.deck_skip)),
            year_unknown=year.get("unknown", base.year_unknown),
        )


def load(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        return Config({})
    return Config(tomllib.loads(path.read_text()))


def write_default(path: Path = CONFIG_PATH, *, force: bool = False) -> bool:
    """Write the annotated default config; returns False if one already exists."""
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_TOML)
    return True
