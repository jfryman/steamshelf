"""Turning game metadata into collection names.

The default naming matches Depressurizer's AutoCat output -- ``(HLTB) 10-20``,
``(Score) Very Positive`` -- so steamshelf extends a library that tool has
already organised instead of building a parallel set of collections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .hltb import HltbResult
from .steamapi import DECK_CATEGORIES, REVIEW_TIERS, AppMetadata

# (upper bound in hours, label).  The last bucket is open-ended.  Labels keep
# Depressurizer's leading space so collections sort numerically in the client.
DEFAULT_HLTB_BUCKETS: list[tuple[float, str]] = [
    (5, " 0-5"),
    (10, " 5-10"),
    (20, "10-20"),
    (50, "20-50"),
    (float("inf"), "50+"),
]

DEFAULT_NAME_FORMAT = "({prefix}) {value}"

HLTB = "hltb"
PLATFORM = "platform"
RATING = "rating"
DECK = "deck"
YEAR = "year"

FAMILIES = (HLTB, PLATFORM, RATING, DECK, YEAR)


@dataclass
class RuleConfig:
    name_format: str = DEFAULT_NAME_FORMAT
    prefixes: dict[str, str] = field(
        default_factory=lambda: {
            HLTB: "HLTB",
            PLATFORM: "Platform",
            RATING: "Score",
            DECK: "Deck",
            YEAR: "Year",
        }
    )
    enabled: dict[str, bool] = field(
        default_factory=lambda: {
            HLTB: True,
            PLATFORM: True,
            RATING: True,
            DECK: True,
            YEAR: True,
        }
    )

    hltb_style: str = "main"  # main | main_extra | completionist | all
    hltb_buckets: list[tuple[float, str]] = field(
        default_factory=lambda: list(DEFAULT_HLTB_BUCKETS)
    )
    hltb_unknown: str = "Unknown"

    # Steam scores computed from a handful of reviews are noise.
    min_reviews: int = 25
    rating_unrated: str = "Unrated"
    # Every family that can legitimately come back with no answer needs a bucket
    # to say so.  Without one the game joins no collection for that family, and
    # needs_filing() keeps flagging it on every run -- it never settles.
    deck_unknown: str = "Unknown"
    year_unknown: str = "Unknown"
    # Deck states to file nothing for. Empty by default; set to ["Unknown"] to
    # go back to leaving untested games out of the Deck family entirely.
    deck_skip: tuple[str, ...] = ()
    platform_labels: tuple[str, ...] = ("Windows", "Mac", "Linux")

    def label(self, family: str, value: str) -> str:
        prefix = self.prefixes.get(family, "")
        if not prefix:
            return value
        return self.name_format.format(prefix=prefix, value=value)

    def active_families(self) -> tuple[str, ...]:
        return tuple(f for f in FAMILIES if self.enabled.get(f))

    def family_prefix(self, family: str) -> str:
        """The literal string every collection in this family starts with."""
        prefix = self.prefixes.get(family, "")
        if not prefix:
            return ""
        rendered = self.name_format.format(prefix=prefix, value="\x00")
        return rendered.split("\x00")[0]

    def family_of(self, collection_name: str) -> str | None:
        for family in self.active_families():
            marker = self.family_prefix(family)
            if marker and collection_name.startswith(marker):
                return family
        return None

    def owns(self, collection_name: str) -> bool:
        return self.family_of(collection_name) is not None

    def known_labels(self, family: str) -> set[str]:
        """Every collection name this config is capable of producing for a family."""
        if family == HLTB:
            values = {label for _upper, label in self.hltb_buckets} | {self.hltb_unknown}
        elif family == PLATFORM:
            values = set(self.platform_labels)
        elif family == RATING:
            values = set(REVIEW_TIERS) | {self.rating_unrated}
        elif family == DECK:
            values = (set(DECK_CATEGORIES.values()) | {self.deck_unknown}) - set(self.deck_skip)
        elif family == YEAR:
            values = {self.year_unknown}
        else:
            return set()
        return {self.label(family, value) for value in values}

    def can_produce(self, collection_name: str) -> bool:
        """True if steamshelf would ever create this exact collection itself.

        Collections that merely share a family prefix -- "(Platform) SteamOS"
        left behind by another tool, say -- are read but never written to, so a
        run cannot quietly empty them.
        """
        family = self.family_of(collection_name)
        if family is None:
            return False
        if family == YEAR:
            marker = self.family_prefix(YEAR)
            suffix = collection_name[len(marker) :]
            # A bare "(Year)" left by another tool has no suffix and is not ours.
            return bool(re.fullmatch(r"(19|20)\d{2}", suffix)) or suffix == self.year_unknown
        return collection_name in self.known_labels(family)


def hltb_bucket(hours: float, config: RuleConfig) -> str:
    for upper, label in config.hltb_buckets:
        if hours < upper:
            return label
    return config.hltb_buckets[-1][1]


def categories_for(
    meta: AppMetadata, hltb: HltbResult | None, config: RuleConfig
) -> dict[str, list[str]]:
    """Collection names a game should belong to, grouped by category family."""
    result: dict[str, list[str]] = {}

    if config.enabled.get(HLTB):
        hours = hltb.hours(config.hltb_style) if hltb else 0.0
        value = hltb_bucket(hours, config) if hours > 0 else config.hltb_unknown
        result[HLTB] = [config.label(HLTB, value)]

    if config.enabled.get(PLATFORM):
        result[PLATFORM] = [config.label(PLATFORM, p) for p in meta.platforms]

    if config.enabled.get(RATING):
        rated = meta.review_desc and meta.review_count >= config.min_reviews
        value = meta.review_desc if rated else config.rating_unrated
        result[RATING] = [config.label(RATING, value)]

    if config.enabled.get(DECK):
        deck = meta.deck or config.deck_unknown
        result[DECK] = [] if deck in config.deck_skip else [config.label(DECK, deck)]

    if config.enabled.get(YEAR):
        # HowLongToBeat's release_world is the original release; Steam's
        # release_date is when the game arrived on Steam. Prefer the former.
        value = (hltb.release_year if hltb else 0) or meta.release_year
        year = str(value) if value else config.year_unknown
        result[YEAR] = [config.label(YEAR, year)]

    return result


def flatten(grouped: dict[str, list[str]]) -> set[str]:
    return {name for names in grouped.values() for name in names}
