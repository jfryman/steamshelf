# Project Summary

`steamshelf` is a Python CLI that files a Steam library's uncategorized games
into collections tagged by how long they take to beat (HowLongToBeat), what
platforms they run on plus Steam Deck compatibility, and their overall Steam
review score. It exists because [Depressurizer](https://github.com/Depressurizer/Depressurizer)
is Windows-only and writes `sharedconfig.vdf`, a file modern Steam no longer
stores categories in.

The defining technical problem is that Steam moved library categories into
**collections**, held in cloud config namespace 1 and served by a service called
`CloudConfigStore` that Valve does **not** expose on `api.steampowered.com`. The
only way to read or write them is a Connection Manager (CM) session. So the
project carries three things a scraper normally would not: a modern credential
login (`IAuthenticationService`), a small websocket CM client, and a hand-rolled
protobuf codec whose message schemas were lifted from the descriptors Valve ships
inside `steamclient.so`.

Default collection names deliberately reproduce Depressurizer's AutoCat format -
`(HLTB) 10-20`, `(Score) Very Positive` - so a library that tool already organized
is extended rather than duplicated. Writes go to a live Steam account, so the
safety machinery (dry-run planning, snapshot-before-upload, and a rule that
steamshelf never writes to a collection it could not itself have created) is
load-bearing, not decoration.

See [lode-map.md](lode-map.md) for the full index.

Domain entry points:
- [steam-auth/summary.md](steam-auth/summary.md) - logging in and keeping a token
- [cm/summary.md](cm/summary.md) - the connection manager client and wire format
- [collections/summary.md](collections/summary.md) - what a collection is, and who owns it
- [metadata/summary.md](metadata/summary.md) - the two scrapers and their cache
- [pipeline/summary.md](pipeline/summary.md) - selection, planning, applying
