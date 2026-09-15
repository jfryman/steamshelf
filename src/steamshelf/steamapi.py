"""Steam library and storefront lookups.

Valve exposes no bulk metadata endpoint to the open web, so per-app details and
review summaries are fetched one app at a time and cached aggressively.  The
storefront rate-limits at roughly 200 requests per five minutes, so requests are
paced and a 429 backs off rather than failing the run.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from . import http
from .cache import Cache

STORE = "https://store.steampowered.com"
API = "https://api.steampowered.com"

APPDETAILS_TTL = 30 * 24 * 3600  # platforms and genres barely move
REVIEWS_TTL = 7 * 24 * 3600  # review scores drift
DECK_TTL = 14 * 24 * 3600

# Steam's own wording for review_score_desc, worst to best.
REVIEW_TIERS = [
    "Overwhelmingly Negative",
    "Very Negative",
    "Negative",
    "Mostly Negative",
    "Mixed",
    "Mostly Positive",
    "Positive",
    "Very Positive",
    "Overwhelmingly Positive",
]

DECK_CATEGORIES = {0: "Unknown", 1: "Unsupported", 2: "Playable", 3: "Verified"}


@dataclass
class OwnedGame:
    appid: int
    name: str
    playtime_minutes: int = 0


@dataclass
class AppMetadata:
    appid: int
    name: str = ""
    app_type: str = ""
    windows: bool = False
    mac: bool = False
    linux: bool = False
    deck: str = "Unknown"
    review_desc: str = ""
    review_positive_pct: int = 0
    review_count: int = 0
    metacritic: int = 0
    release_year: int = 0
    genres: list[str] = field(default_factory=list)

    @property
    def platforms(self) -> list[str]:
        out = []
        if self.windows:
            out.append("Windows")
        if self.mac:
            out.append("Mac")
        if self.linux:
            out.append("Linux")
        return out


class SteamClient:
    def __init__(self, cache: Cache, *, request_delay: float = 1.4):
        self.cache = cache
        self.request_delay = request_delay
        self._last_store_call = 0.0

    # -- library -------------------------------------------------------------

    def owned_games(self, steamid: int, access_token: str) -> list[OwnedGame]:
        data = http.get_json(
            f"{API}/IPlayerService/GetOwnedGames/v1/",
            params={
                "access_token": access_token,
                "steamid": steamid,
                "include_appinfo": 1,
                "include_played_free_games": 1,
                "skip_unvetted_apps": 0,
            },
        )["response"]
        return [
            OwnedGame(
                appid=int(g["appid"]),
                name=g.get("name", f"App {g['appid']}"),
                playtime_minutes=int(g.get("playtime_forever", 0)),
            )
            for g in data.get("games", [])
        ]

    # -- storefront ----------------------------------------------------------

    def _throttle(self) -> None:
        wait = self.request_delay - (time.monotonic() - self._last_store_call)
        if wait > 0:
            time.sleep(wait)
        self._last_store_call = time.monotonic()

    def _store_get(self, url: str, **kwargs: object) -> object:
        for attempt in range(4):
            self._throttle()
            try:
                return http.get_json(url, retries=1, **kwargs)  # type: ignore[arg-type]
            except http.HttpError as exc:
                if exc.status != 429 or attempt == 3:
                    raise
                # The storefront's window is five minutes; backing off hard beats
                # hammering it and getting the whole run blocked.
                time.sleep(20 * (attempt + 1))
        raise RuntimeError("unreachable")

    def app_details(self, appid: int) -> dict | None:
        cached = self.cache.get("appdetails", appid, APPDETAILS_TTL)
        if cached is not None:
            return cached or None
        payload = self._store_get(
            f"{STORE}/api/appdetails",
            params={
                "appids": appid,
                "filters": "basic,platforms,metacritic,genres,release_date",
                "l": "english",
                "cc": "us",
            },
        )
        entry = (payload or {}).get(str(appid), {})  # type: ignore[union-attr]
        data = entry.get("data") if entry.get("success") else None
        self.cache.set("appdetails", appid, data or {})
        return data

    def reviews(self, appid: int) -> dict | None:
        cached = self.cache.get("reviews", appid, REVIEWS_TTL)
        if cached is not None:
            return cached or None
        payload = self._store_get(
            f"{STORE}/appreviews/{appid}",
            params={
                "json": 1,
                "language": "all",
                "purchase_type": "all",
                "num_per_page": 0,
                "filter": "all",
            },
        )
        summary = (payload or {}).get("query_summary") if payload else None  # type: ignore[union-attr]
        self.cache.set("reviews", appid, summary or {})
        return summary

    def deck_compatibility(self, appid: int) -> str:
        cached = self.cache.get("deck", appid, DECK_TTL)
        if cached is not None:
            return cached or "Unknown"
        try:
            payload = self._store_get(
                f"{STORE}/saleaction/ajaxgetdeckappcompatibilityreport",
                params={"nAppID": appid, "l": "english"},
            )
            results = (payload or {}).get("results") or {}  # type: ignore[union-attr]
            category = DECK_CATEGORIES.get(int(results.get("resolved_category", 0)), "Unknown")
        except (http.HttpError, ValueError, TypeError):
            category = "Unknown"
        self.cache.set("deck", appid, category)
        return category

    def metadata(self, appid: int, name: str = "", *, want_deck: bool = True) -> AppMetadata:
        meta = AppMetadata(appid=appid, name=name)

        details = self.app_details(appid)
        if details:
            meta.name = details.get("name") or name
            meta.app_type = details.get("type", "")
            platforms = details.get("platforms") or {}
            meta.windows = bool(platforms.get("windows"))
            meta.mac = bool(platforms.get("mac"))
            meta.linux = bool(platforms.get("linux"))
            meta.metacritic = int((details.get("metacritic") or {}).get("score", 0) or 0)
            meta.genres = [g["description"] for g in details.get("genres") or []]
            release = details.get("release_date") or {}
            if not release.get("coming_soon"):
                match = re.search(r"(19|20)\d{2}", release.get("date", "") or "")
                if match:
                    meta.release_year = int(match.group(0))

        summary = self.reviews(appid)
        if summary:
            meta.review_desc = summary.get("review_score_desc", "")
            total = int(summary.get("total_reviews", 0) or 0)
            positive = int(summary.get("total_positive", 0) or 0)
            meta.review_count = total
            meta.review_positive_pct = round(100 * positive / total) if total else 0

        if want_deck:
            meta.deck = self.deck_compatibility(appid)
        return meta
