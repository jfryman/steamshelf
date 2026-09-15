# Practices

Patterns this project holds to.

## Verify Steam's surface, never assume it

Every claim about a Steam endpoint here was probed before being designed around.
The habit paid for itself repeatedly:

- `ICloudConfigStore` returns `404`, not `401` - it is absent from the Web API,
  not merely unauthorized. That distinction dictated the whole architecture.
- `sharedconfig.vdf` on a current install has no category data at all.
- `appdetails` rejects multiple appids; `IStoreBrowse` is client-only.

When something looks like it should work, spend the two minutes with `curl` before
spending an hour on the code.

## Prefer extracting a schema over guessing one

Message layouts come from the Steam client on disk - the field maps in
`steamui/chunk~*.js` and the `FileDescriptorProto` blobs in `steamclient.so` - not
from memory or a blog post. See [cm/wire-codec.md](cm/wire-codec.md) for both
techniques.

## Dependency-light on purpose

Stdlib plus `websocket-client`. RSA is `pow()`. Protobuf is 150 hand-written
lines. The cache is `sqlite3`. This is not minimalism for its own sake: the
obvious dependency (`ValvePython/steam`) pins `protobuf<=3.20` and does not
install on a current Python, and inheriting that would have been worse than the
code it saved.

## A failed request is not a negative result

The single most consequential bug class here. "Asked and there is nothing" gets
cached and acted on; "could not ask" must leave state untouched and be retried.
Applies to the metadata cache, to HLTB lookups, and to the plan's `retry_later`
bucket. See [metadata/caching.md](metadata/caching.md).

## One bad item must not end a long sweep

A library sweep costs an hour. Per-game failures are collected, reported, and
retried next run - never raised through the loop. The regression test
`test_one_failed_lookup_does_not_end_the_sweep` exists because this was learned
the hard way at game 357 of 753.

## Read broadly, write narrowly

steamshelf reads every collection sharing a managed prefix so it knows what is
already filed, but writes only to collections it could itself have created. The
two predicates are `owns()` and `can_produce()` and they are deliberately not the
same thing. See [collections/naming-and-ownership.md](collections/naming-and-ownership.md).

## Compatibility with an existing library beats naming taste

Default collection names reproduce Depressurizer's, down to the leading space in
`(HLTB)  0-5` and the spelling `Mac`. They are a contract with data already on the
user's account, not a style choice.

## Dry run is the real path minus the write

`plan` and `apply` execute the identical code up to `apply_plan`. A dry run that
approximates the real thing is worth little.

## Tests cover logic, not the network

`pytest` runs offline in well under a second: the wire codec round-trips, title
matching, bucket boundaries, ownership predicates, plan deltas, sweep resilience.
Network behaviour is verified by hand against the live account and written down
here instead - see [metadata/howlongtobeat.md](metadata/howlongtobeat.md) for the
kind of measurement that belongs in the lode rather than in a flaky test.
