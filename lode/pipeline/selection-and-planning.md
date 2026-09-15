# Selection and Planning

`src/steamshelf/engine.py`.

## "Uncategorized" means missing a family

Not "in zero collections". A game is a target when **any active family** has no
collection holding it:

```python
def needs_filing(appid, membership, config):
    seen = {config.family_of(name) for name in membership.get(appid, set())}
    return any(family not in seen for family in config.active_families())
```

This is what makes the tool cheap to re-run: buy a game, run again, and only that
game is looked up. `--all` overrides it and reconsiders everything.

**Consequence worth knowing.** Enabling a new family makes the entire library
"uncategorized" at once, because no game has a collection in it yet. Turning on
`deck` for a Depressurizer-organized library meant all 753 apps needed a sweep.
That is correct but expensive; it is a one-time cost per family.

Membership is computed only from collections `config.owns()`, and built-in
collections never count - being in `Favorites` does not mean a game is filed.

## Desired categories

`rules.categories_for()` returns a dict keyed by family, not a flat set:

```python
{"hltb": ["(HLTB)  5-10"],
 "platform": ["(Platform) Windows", "(Platform) Linux"],
 "rating": ["(Score) Overwhelmingly Positive"],
 "deck": ["(Deck) Verified"]}
```

Grouping is load-bearing: a family **present but empty** (`"deck": []`) means
"we evaluated this and the answer is nothing". A family **absent** means "we could
not evaluate this", which suppresses both additions and removals for it.

## Removals

```python
if family and self.desired.get(family) is not None and config.can_produce(name):
    stale.add(name)
```

Three conditions, all necessary: the collection belongs to a known family; that
family was actually evaluated this run; and the name is one this config could have
created. See [../collections/naming-and-ownership.md](../collections/naming-and-ownership.md).

This is what moves a game between buckets when HowLongToBeat data changes, and
what reconciles `(Score) Positive` -> `(Score) Very Positive` after years of
review drift.

## Failure buckets

| Bucket | Meaning | Effect |
|---|---|---|
| `skipped` | not a game, or no store page | never categorized |
| `retry_later` | transient lookup failure | keeps current categories; next run retries |

A per-game exception during metadata lookup goes to `retry_later` and the sweep
continues:

```python
try:
    meta = steam.metadata(game.appid, game.name, want_deck=want_deck)
except Exception as exc:
    plan.retry_later.append((game, f"Steam lookup failed: {exc}"))
    continue
```

The broad `except` is deliberate and covered by a regression test
(`test_one_failed_lookup_does_not_end_the_sweep`). An hour-long sweep is too
expensive to discard over one app.

## Applying

`apply_plan` mutates a `CollectionSet` in place and returns only the collections
whose membership actually changed, so an upload carries the minimum. Collections
outside the plan are never serialized.

Related: [apply-and-safety.md](apply-and-safety.md)
