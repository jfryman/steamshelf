# Collection Model

`src/steamshelf/collections.py`.

## On-the-wire shape

Each collection is one namespace entry whose key is `user-collections.<id>` and
whose value is a JSON *string*:

```json
{"id":"uc-1C8DCc7LwTUf","name":"Shooters","added":[70,220,620],"removed":[]}
```

A dynamic collection carries `filterSpec` instead of a meaningful `added`:

```json
{"id":"uc-xyz","name":"Unplayed","added":[],"removed":[],"filterSpec":{"nFormatVersion":2,...}}
```

Built-in collections use fixed ids and are shaped identically:

```json
{"id":"favorite","name":"Favorites","added":[1086940,...],"removed":[]}
```

A deleted collection is an entry with `is_deleted: true` and **no `value` key** -
reading `entry["value"]` on one raises `KeyError`, which is worth remembering when
writing ad-hoc scripts against a raw dump.

## Model

```python
@dataclass
class Collection:
    id: str; name: str
    added: list[int]; removed: list[int]
    filter_spec: Any = None
    entry_version: int = 0
    is_deleted: bool = False

    @property
    def editable(self):
        return not self.is_deleted and not self.is_dynamic and not self.is_builtin
```

`editable` is structural - "is this the kind of thing that can be hand-edited at
all". It is *not* permission to write; that is `RuleConfig.can_produce`. See
[naming-and-ownership.md](naming-and-ownership.md).

## Invariants

- **`added` is written sorted and de-duplicated.** Keeps diffs against a snapshot
  readable and uploads idempotent.
- **`removed` is preserved, never synthesised.** It is Steam's mechanism for
  excluding a game from a dynamic collection; steamshelf has no business there.
- **`filterSpec` round-trips untouched** if a dynamic collection is ever
  serialized, so nothing is lost by accident.
- **New ids are `uc-` + 12 random alphanumerics**, matching the client's format.
- **`CollectionSet.ensure(name)` matches by name, not id.** This is what makes a
  run merge into an existing `(HLTB) 10-20` rather than creating a second one.

## Parsing contract

`parse_entry` returns `None` for any key outside `user-collections.` and for
unparseable JSON, so a caller can hand it every entry in the namespace. That is
deliberate: namespace 1 is roughly two-thirds non-collection data.

Related: [../cm/cloudconfigstore.md](../cm/cloudconfigstore.md)
