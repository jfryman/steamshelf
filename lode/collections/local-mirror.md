# Local Mirror

The running Steam client keeps a copy of namespace 1 on disk. steamshelf can read
it with `--source local`, which needs no login and no CM connection.

```
~/.local/share/Steam/userdata/<steamid3>/config/cloudstorage/
    cloud-storage-namespace-1.json        # the entries
    cloud-storage-namespaces.json         # [[namespace_id, version], ...]
```

`store.STEAM_DIRS` also covers `~/.steam/steam`, the Flatpak path, and macOS's
`~/Library/Application Support/Steam`.

## Shape

An array of `[key, entry]` pairs rather than a bare list of entries:

```json
[
  ["GameReleased", {"key": "GameReleased", "timestamp": 1767663634, "value": "{...}", "version": "1166"}],
  ["user-collections.favorite", {"key": "user-collections.favorite", "value": "{...}", "version": "997"}]
]
```

So reading it is `[entry for _key, entry in raw]`. The namespace version lives in
the sibling `cloud-storage-namespaces.json` as `[[3,"0"],[1,"1181"]]`.

## What it is and is not for

**Good for:** inspecting collections offline, `steamshelf collections --source
local`, sanity-checking a cloud read, and as a free backup of pre-run state.

**Not a write target.** steamshelf never writes this file. A running client owns
it, syncs from the cloud, and would overwrite anything put there. All writes go
through [../cm/cloudconfigstore.md](../cm/cloudconfigstore.md).

## localconfig.vdf: which apps the client knows

A sibling file, `config/localconfig.vdf`, carries per-app client state under
`Software/Valve/Steam/apps`. `store.client_known_appids()` brace-matches that
block and pulls the appids out:

```python
block = _apps_block(local.read_text(errors="replace"))
return {int(m.group(1)) for m in re.finditer(r'^\t*"(\d{1,8})"\s*$', block, re.M)}
```

Brace matching is necessary, not fussiness - a naive scan forward from `"apps"`
runs on into `friends` and other sections and harvests steamids as appids.

This is how family-shared and never-launched free-to-play titles are found; see
[../pipeline/selection-and-planning.md](../pipeline/selection-and-planning.md).

## Related dead end: sharedconfig.vdf

`userdata/<steamid3>/7/remote/sharedconfig.vdf` is where Depressurizer wrote
categories. On a current install it contains no `Apps`/tags section at all - only
`Tools`, `FriendsUI` and `JSClientStorage`. Writing categories there does nothing.
This was verified, not assumed, and is the reason the CM client exists.

Related: [collection-model.md](collection-model.md)
