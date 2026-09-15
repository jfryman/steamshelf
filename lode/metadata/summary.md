# Metadata

Where the three category dimensions come from, and why both sources are scrapes.

```mermaid
flowchart LR
    G["owned game"] --> SD["store appdetails<br/>platforms, type, year"]
    G --> SR["store appreviews<br/>review_score_desc, counts"]
    G --> DK["deck compat report"]
    G --> H["HowLongToBeat<br/>completion times"]
    SD & SR & DK --> M["AppMetadata"]
    H --> R["HltbResult"]
    M & R --> C["cache.sqlite3"]
```

Neither Steam nor HowLongToBeat offers a supported bulk API to the open web, so
both are per-app, paced, and cached. A first full sweep of ~750 games takes
roughly an hour; subsequent runs are minutes.

## Files

| File | Contents |
|---|---|
| [steam-storefront.md](steam-storefront.md) | appdetails, appreviews, Deck, rate limits |
| [howlongtobeat.md](howlongtobeat.md) | The init-token dance and title matching |
| [caching.md](caching.md) | TTLs and what invalidation means here |

Related: [../pipeline/summary.md](../pipeline/summary.md)
