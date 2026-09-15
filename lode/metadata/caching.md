# Caching

`src/steamshelf/cache.py`. One SQLite file at
`~/.cache/steamshelf/metadata.sqlite3`, a single `entries` table keyed
`(scope, key)` with a `fetched` timestamp.

```sql
CREATE TABLE entries (scope TEXT, key TEXT, value TEXT, fetched INTEGER,
                      PRIMARY KEY (scope, key));
```

## Scopes and TTLs

| Scope | TTL | Rationale |
|---|---|---|
| `appdetails` | 30 days | platforms and type barely change |
| `reviews` | 7 days | review scores drift continuously |
| `deck` | 14 days | Valve re-tests occasionally |
| `hltb` | 60 days | community averages move slowly |

## Negative caching

A confirmed "no data" is cached as an empty object, so a delisted app or a game
genuinely absent from HowLongToBeat is not re-fetched every run:

```python
self.cache.set("hltb", appid, {})   # searched, no acceptable match
```

**A failed request is never cached.** Empty means "asked and there is nothing";
absent means "never successfully asked". Conflating them is the bug described in
[howlongtobeat.md](howlongtobeat.md).

## Why it matters operationally

The cache is what makes an interrupted sweep cheap to resume. After a run died at
game 357, the retry covered those 357 in about two minutes before reaching new
work. There is no checkpoint file and none is needed - the cache *is* the
checkpoint.

`steamshelf cache` prints per-scope counts; `--clear [--scope X]` empties it.
Clearing `reviews` is the normal way to force a score refresh.

Related: [steam-storefront.md](steam-storefront.md), [howlongtobeat.md](howlongtobeat.md)
