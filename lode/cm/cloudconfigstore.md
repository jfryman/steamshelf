# CloudConfigStore

The service that owns collections. Two methods matter.

## Messages

```proto
message CCloudConfigStore_Entry {
  optional string key        = 1;   // "user-collections.uc-AbCdEf"
  optional bool   is_deleted = 2;
  optional string value      = 3;   // JSON, see ../collections/collection-model.md
  optional fixed32 timestamp = 4;
  optional uint64 version    = 5;   // per-entry, server-assigned
}
message CCloudConfigStore_NamespaceData {
  optional uint32 enamespace = 1;   // 1 for user settings
  optional uint64 version    = 2;   // namespace version
  repeated CCloudConfigStore_Entry entries = 3;
  optional uint64 horizon    = 4;
}
message CCloudConfigStore_NamespaceVersion { uint32 enamespace = 1; uint64 version = 2; }

// CloudConfigStore.Download#1
message CCloudConfigStore_Download_Request  { repeated CCloudConfigStore_NamespaceVersion versions = 1; }
message CCloudConfigStore_Download_Response { repeated CCloudConfigStore_NamespaceData data = 1; }
// CloudConfigStore.Upload#1
message CCloudConfigStore_Upload_Request    { repeated CCloudConfigStore_NamespaceData data = 1; }
message CCloudConfigStore_Upload_Response   { repeated CCloudConfigStore_NamespaceVersion versions = 1; }
```

## Download

Requesting `version = 0` returns the whole namespace, not a delta. That is what
steamshelf always does; incremental sync is not worth the complexity for a tool
that runs occasionally.

```python
data = client.download_namespace(enamespace=1, since_version=0)
# {"enamespace": 1, "version": 1182, "entries": [...], "horizon": ...}
```

A real account's namespace 1 holds far more than collections - roughly 176 entries
of which ~62 are `user-collections.*`, the rest being things like `GameReleased`
and `NewContentRollup_<appid>`. Filtering by key prefix is mandatory.

## Upload

An upload is an **upsert of the entries you send**, not a replacement of the
namespace. Entries you omit are untouched. But each entry's `value` replaces that
collection's JSON wholesale, so a collection must be sent complete.

```python
new_version = client.upload_entries(
    [c.to_entry() for c in changed_collections],
    enamespace=1,
    version=downloaded_namespace_version,
)
```

Observed behaviour, confirmed against a live account:

- The namespace version increments by one per successful upload (1181 -> 1182).
- Per-entry `version` may be omitted; the server assigns it.
- `timestamp` is set to `int(time.time())` on write.
- Deleting a collection means an entry with `is_deleted = True` and no `value`.
  Deleted entries persist in the namespace as tombstones.
- Changes reach a running Steam client on its next sync, not instantly.

## Contract with the rest of the tool

`store.CloudStore` is the only thing that calls these. It re-downloads immediately
before every upload so the plan is applied to current data - see
[../pipeline/apply-and-safety.md](../pipeline/apply-and-safety.md).

Related: [frame-protocol.md](frame-protocol.md),
[../collections/collection-model.md](../collections/collection-model.md)
