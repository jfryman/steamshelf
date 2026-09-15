# Roadmap

Open work and pending decisions. Not a changelog.

## Decided, not built

- **`year` family off by default.** The code supports `(Year) 2019` and the user's
  library has those collections from Depressurizer, stopping at 2023. Turning it
  on would refile the whole library on a dimension that was not asked for. Left to
  the user via config.
- **`(Platform) SteamOS` left alone.** Depressurizer used it as a duplicate of the
  Linux flag. The modern equivalent is Deck compatibility, which is its own
  family. The old collection is read, never written.

## Worth considering

- **Publish to GitHub.** The repo is local only; `gh` is not authenticated on this
  machine. Nothing blocks it.
- **Parallel metadata fetching.** A sweep is ~4.4 s per uncached game, almost all
  of it sleeping between paced requests. Two or three workers against the
  storefront would cut a first run substantially. HowLongToBeat should stay
  serial - it already rejects roughly one request in ten under a single-threaded
  load.
- **Persist the plan.** A sweep that completes and then fails at the upload -
  which a fleet-wide CM 502 caused - discards the computed plan and has to
  recompute it. The cache keeps that cheap (minutes, not an hour), so this is
  convenience rather than necessity, but writing the plan to disk before
  connecting would make the retry instant.
- **Resume reporting.** A run that dies mid-sweep prints nothing. A partial-plan
  summary on interrupt would make that less opaque.
- **`--prune` for empty managed collections.** A bucket that ends up with zero
  games stays as an empty collection. Harmless, slightly untidy.
- **Genre and tag families.** Depressurizer had them. The data is in `appdetails`
  (`genres`) and already parsed into `AppMetadata`, so this is mostly a rules
  question, not a scraping one.

## Known rough edges

- Steam running during `apply` is tolerated, not guaranteed safe. See
  [../pipeline/apply-and-safety.md](../pipeline/apply-and-safety.md).
- HowLongToBeat's `/api/search/site` path and its init-token scheme are
  undocumented and have moved before. If searches start failing wholesale,
  re-read the site's JS chunks for a `fetch("/api/...")` call; that is how the
  current scheme was found. See [../metadata/howlongtobeat.md](../metadata/howlongtobeat.md).
- Title matching accepts at confidence 0.72. `Half-Life` vs `Half-Life 2` scores
  0.90 on raw similarity and is only separated by the sequel-marker guard. A
  library with many numbered series is the place this would break first.
