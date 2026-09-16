"""HowLongToBeat lookups.

HowLongToBeat has no public API.  The site's own search calls
``/api/search/site`` with a short-lived token handed out by
``/api/search/site/init``, plus a rotating header/body key pair; this module
does the same thing the browser does.  That endpoint moves from time to time, so
:func:`discover_endpoint` re-reads the site's JS bundle when the known path
starts returning 404.
"""

from __future__ import annotations

import difflib
import re
import time
from dataclasses import dataclass

from . import http
from .cache import Cache

BASE = "https://howlongtobeat.com"
SEARCH_PATH = "/api/search/site"
INIT_PATH = "/api/search/site/init"
TOKEN_TTL = 240.0
TOKEN_SETTLE = 1.2
SEARCH_ATTEMPTS = 4
RESULT_TTL = 60 * 24 * 3600

# Editions and platform suffixes that only ever hurt a title match.
NOISE = re.compile(
    r"\b(goty|game of the year|definitive|enhanced|complete|deluxe|ultimate|remastered|"
    r"remake|anniversary|collectors?|director'?s cut|gold|premium|legendary|special)\b"
    r"(\s+(edition|bundle|pack))?",
    re.I,
)
TRAILING_JUNK = re.compile(r"\b(vr|hd|steam edition|pc edition|windows edition)\b$", re.I)

# Tokens that distinguish a sequel from its predecessor; a match has to agree on
# these even when one side carries a subtitle the other does not.
ROMAN = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii"}


def _sequel_markers(tokens: list[str]) -> list[str]:
    return [t for t in tokens if t.isdigit() or t in ROMAN]


def title_similarity(query: str, candidate: str) -> float:
    """How confident we are that ``candidate`` names the same game as ``query``."""
    score = difflib.SequenceMatcher(None, query, candidate).ratio()
    q_tokens, c_tokens = query.split(), candidate.split()
    if not q_tokens or not c_tokens:
        return score
    # HowLongToBeat often lists a game under a shorter name than Steam does
    # ("Disco Elysium" vs "Disco Elysium - The Final Cut").  Treat one title
    # being a leading run of the other as a strong match, but only when neither
    # side carries a sequel number the other lacks.
    shorter, longer = sorted((q_tokens, c_tokens), key=len)
    if longer[: len(shorter)] == shorter and _sequel_markers(q_tokens) == _sequel_markers(c_tokens):
        score = max(score, 0.95)
    return score


def normalize(title: str) -> str:
    text = title.lower().replace("&", "and")
    # Drop apostrophes rather than splitting on them, so "Baldur's" stays one word.
    text = re.sub(r"[’'ʼ]", "", text)
    text = re.sub(r"[™®©]", "", text)
    text = NOISE.sub(" ", text)
    text = TRAILING_JUNK.sub(" ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


@dataclass
class HltbResult:
    game_id: int
    name: str
    main_hours: float = 0.0
    main_extra_hours: float = 0.0
    completionist_hours: float = 0.0
    all_styles_hours: float = 0.0
    # Original worldwide release year. Steam's own release_date is the date the
    # game was listed on Steam, which for anything older than the store itself
    # is wrong -- Indiana Jones and the Last Crusade (1989) reads as 2009.
    release_year: int = 0
    steam_appid: int = 0
    confidence: float = 0.0

    def hours(self, style: str) -> float:
        return {
            "main": self.main_hours,
            "main_extra": self.main_extra_hours,
            "completionist": self.completionist_hours,
            "all": self.all_styles_hours,
        }.get(style, self.main_hours)

    @property
    def url(self) -> str:
        return f"{BASE}/game/{self.game_id}"


class HltbError(RuntimeError):
    pass


class HltbClient:
    def __init__(self, cache: Cache, *, request_delay: float = 0.6):
        self.cache = cache
        self.request_delay = request_delay
        self._token: dict[str, str] | None = None
        self._token_at = 0.0
        self._last_call = 0.0

    # -- request plumbing ----------------------------------------------------

    def _security_token(self, force: bool = False) -> dict[str, str]:
        if not force and self._token and time.time() - self._token_at < TOKEN_TTL:
            return self._token
        payload = http.get_json(
            f"{BASE}{INIT_PATH}",
            params={"t": int(time.time() * 1000)},
            headers={"Referer": f"{BASE}/", "Origin": BASE},
        )
        if "token" not in payload:
            raise HltbError("HowLongToBeat did not issue a search token")
        self._token = {
            "token": payload["token"],
            "hp_key": payload.get("hpKey") or "",
            "hp_val": str(payload.get("hpVal") or ""),
        }
        self._token_at = time.time()
        # A token used the instant it is issued is usually rejected as an
        # "invalid fingerprint"; letting it settle first makes searches reliable.
        time.sleep(TOKEN_SETTLE)
        return self._token

    def _throttle(self) -> None:
        wait = self.request_delay - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _search_payload(self, terms: list[str], page: int = 1) -> dict:
        return {
            "searchType": "games",
            "searchTerms": terms,
            "searchPage": page,
            "size": 20,
            "searchOptions": {
                "games": {
                    "userId": 0,
                    "platform": "",
                    "sortCategory": "popular",
                    "rangeCategory": "main",
                    "rangeTime": {"min": None, "max": None},
                    "gameplay": {
                        "perspective": "",
                        "flow": "",
                        "genre": "",
                        "difficulty": "",
                    },
                    "year": "",
                    "modifier": "",
                },
                "users": {"sortCategory": "postcount"},
                "lists": {"sortCategory": "follows"},
                "filter": "",
                "sort": 0,
                "randomizer": 0,
            },
            "useCache": True,
        }

    def _raw_search(self, terms: list[str]) -> list[dict]:
        last: Exception | None = None
        for attempt in range(SEARCH_ATTEMPTS):
            # The first retry reuses the token (these 403s are usually transient);
            # later ones start a fresh session.
            token = self._security_token(force=attempt >= 2)
            body = self._search_payload(terms)
            if token["hp_key"]:
                body[token["hp_key"]] = token["hp_val"]
            self._throttle()
            try:
                payload = http.request(
                    f"{BASE}{SEARCH_PATH}",
                    method="POST",
                    json_body=body,
                    headers={
                        "Referer": f"{BASE}/?q={'+'.join(terms)}",
                        "Origin": BASE,
                        "x-auth-token": token["token"],
                        "x-hp-key": token["hp_key"],
                        "x-hp-val": token["hp_val"],
                    },
                    retries=1,
                ).json()
            except http.HttpError as exc:
                if exc.status not in (401, 403, 429):
                    raise HltbError(f"HowLongToBeat search failed: {exc}") from None
                last = exc
                time.sleep(1.0 + attempt)
                continue
            return payload.get("data", [])
        raise HltbError(f"HowLongToBeat kept rejecting the search session: {last}")

    # -- lookups -------------------------------------------------------------

    def search(self, title: str) -> list[HltbResult]:
        terms = [t for t in normalize(title).split() if t]
        if not terms:
            return []
        results = []
        for row in self._raw_search(terms):
            results.append(
                HltbResult(
                    game_id=int(row.get("game_id", 0)),
                    name=row.get("game_name", ""),
                    # HowLongToBeat reports completion times in seconds.
                    main_hours=round(row.get("comp_main", 0) / 3600, 1),
                    main_extra_hours=round(row.get("comp_plus", 0) / 3600, 1),
                    completionist_hours=round(row.get("comp_100", 0) / 3600, 1),
                    all_styles_hours=round(row.get("comp_all", 0) / 3600, 1),
                    release_year=int(row.get("release_world", 0) or 0),
                    steam_appid=int(row.get("profile_steam", 0) or 0),
                )
            )
        return results

    def lookup(self, appid: int, title: str) -> HltbResult | None:
        """Best match for a Steam app, preferring HLTB's own Steam appid link."""
        cached = self.cache.get("hltb", appid, RESULT_TTL)
        if cached is not None:
            return HltbResult(**cached) if cached else None

        # A transport failure is not the same as "this game isn't on HLTB", and
        # must not be cached or turned into an Unknown bucket; let it propagate
        # so the caller can leave the game alone and retry on the next run.
        candidates = self.search(title)

        best: HltbResult | None = None
        wanted = normalize(title)
        for candidate in candidates:
            if candidate.steam_appid == appid and appid:
                candidate.confidence = 1.0
                best = candidate
                break
            score = title_similarity(wanted, normalize(candidate.name))
            if best is None or score > best.confidence:
                candidate.confidence = score
                best = candidate

        if best is None or best.confidence < 0.72 or best.hours("all") <= 0:
            self.cache.set("hltb", appid, {})
            return None
        self.cache.set("hltb", appid, best.__dict__)
        return best
