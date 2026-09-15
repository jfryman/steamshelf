# Wire Codec

`src/steamshelf/wire.py`. A ~150-line protobuf encoder/decoder, deliberately
hand-rolled.

## Why not a real protobuf library

`ValvePython/steam` is the obvious dependency and it does not work here. Its
generated `_pb2` modules were produced by an old protoc and raise on import
against modern protobuf:

```
TypeError: Descriptors cannot be created directly.
... your generated code is out of date and must be regenerated with protoc >= 3.19.0
```

The documented workaround is pinning `protobuf<=3.20`, which has no wheels for
current Pythons. steamshelf needs about eight message types in total, so encoding
them directly is less code than vendoring or regenerating bindings, and it removes
a build step and a version conflict permanently.

## Model

Messages are plain dicts keyed by field *name*. A schema maps field number to
`(name, kind)`, optionally `(name, kind, repeated)` or
`(name, kind, repeated, submessage_schema)`:

```python
CLOUD_ENTRY = {
    1: ("key", "string"),
    2: ("is_deleted", "bool"),
    3: ("value", "string"),
    4: ("timestamp", "fixed32"),
    5: ("version", "uint64"),
}
CLOUD_NAMESPACE_DATA = {
    1: ("enamespace", "uint32"),
    2: ("version", "uint64"),
    3: ("entries", "message", True, CLOUD_ENTRY),
    4: ("horizon", "uint64"),
}
```

Supported kinds: `varint bool int32 uint32 int64 uint64 fixed32 fixed64 string
bytes message`.

## Invariants

- **Unknown fields decode to nothing.** Steam adds fields freely; dropping them is
  correct and keeps the schemas minimal.
- **Negative varints sign-extend to 64 bits.** `client_os_type` is `-203`
  (`k_EOSTypeLinuxUnknown`); without this it encodes wrong and logon fails.
- **Fields are emitted in ascending field-number order.** Protobuf does not
  require it, but Steam's own clients do, which keeps captures comparable.
- `None` values are skipped, so optional fields can be passed unconditionally.

## Where the schemas came from

Not from guesswork and not from a public repo - the
`steammessages_cloudconfigstore` proto is not in `SteamDatabase/Protobufs` or
`SteamTracking/Protobufs`. Two authoritative local sources were used:

**1. The Steam client's own JS bundle** carries the field maps for
`CloudConfigStore`:

```
~/.local/share/Steam/steamui/chunk~*.js
```

Search for `getClassName(){return"CCloudConfigStore_Entry"` and read the
`fields:{...}` object immediately before it - it lists each field's number and
reader/writer (`readUint64String`, `readFixed32`, ...).

**2. `steamclient.so` embeds serialized `FileDescriptorProto` blobs.** Locate
`\x0a<len>steammessages_clientserver_login.proto`, walk forward field by field
until the tags stop being valid, and parse the slice with
`google.protobuf.descriptor_pb2.FileDescriptorProto`. This is how
`CMsgClientLogon.access_token = 108` and the full `CMsgProtoBufHeader` layout were
confirmed.

Both techniques are worth repeating if Valve changes a message. The scratch
extractor lived in the session scratchpad, not the repo; rebuild it from this
description rather than hunting for it.

## Verification

`tests/test_wire.py` round-trips scalars, repeated submessages, negative varints
and unknown-field dropping. No network needed.

Related: [frame-protocol.md](frame-protocol.md), [cloudconfigstore.md](cloudconfigstore.md)
