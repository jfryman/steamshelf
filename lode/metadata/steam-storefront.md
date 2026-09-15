# Steam Storefront

`src/steamshelf/steamapi.py`.

## Endpoints

| Purpose | Endpoint | Auth |
|---|---|---|
| Owned games | `api.steampowered.com/IPlayerService/GetOwnedGames/v1/` | access token |
| Platforms, type, year | `store.steampowered.com/api/appdetails` | none |
| Review score | `store.steampowered.com/appreviews/<appid>?json=1` | none |
| Deck compatibility | `store.steampowered.com/saleaction/ajaxgetdeckappcompatibilityreport` | none |

`GetOwnedGames` takes the session's access token, so no Web API key is needed.

## There is no bulk endpoint

Checked, because it would have cut the sweep from an hour to seconds:

- `appdetails?appids=620,8930` -> `400`. Multiple ids only work with
  `filters=price_overview`.
- `IStoreBrowse/GetItems/v1/` -> `404` on `api.steampowered.com`, and the store
  host serves the HTML homepage for it. Client-only, like `ICloudConfigStore`.

So it is one to three requests per app. Accept it and cache hard.

## Rate limiting and resilience

The storefront allows roughly 200 requests per five minutes. `_store_get` paces
calls at `--store-delay` (default 1.4 s) and handles two failure classes:

```python
except http.HttpError as exc:
    if exc.status != 429 or attempt == 3: raise
    time.sleep(20 * (attempt + 1))     # the window is 5 minutes; back off hard
except (OSError, TimeoutError):
    if attempt == 3: raise
    time.sleep(2 * (attempt + 1))      # dropped connection, says nothing about the app
```

**Lesson, learned the expensive way.** The `OSError`/`TimeoutError` arm was
missing, and a read timing out at game 357 of 753 aborted an hour-long sweep with
nothing written. Two fixes came out of it: retry transport errors here, and never
let one app's failure end the sweep - see
[../pipeline/selection-and-planning.md](../pipeline/selection-and-planning.md).

## Field mapping

- `platforms.{windows,mac,linux}` -> `Windows` / `Mac` / `Linux`. Note `Mac`,
  not `macOS`; see [../collections/naming-and-ownership.md](../collections/naming-and-ownership.md).
- `query_summary.review_score_desc` is Steam's own wording and is used verbatim,
  so `(Score) Very Positive` matches what the store page says.
- `resolved_category` 0-3 -> `Unknown` / `Unsupported` / `Playable` / `Verified`.
- `release_date.date` is free text; the year is regex-extracted and skipped when
  `coming_soon` is set.

## Apps that are not games

`type` in `{dlc, demo, music, video, episode, hardware, mod, series}` is skipped,
as is an app with no store page at all (delisted or region-locked), which comes
back as an empty `data` object. Both land in the plan's `skipped` list with a
reason rather than being categorized as a game with no playtime.

Related: [caching.md](caching.md), [howlongtobeat.md](howlongtobeat.md)
