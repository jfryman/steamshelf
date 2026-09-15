# Terminology

Domain language, Steam's and ours.

## Steam concepts

- **Collection** - a named group of games in the Steam library UI. Replaced the
  older "category". Stored in the cloud, not in any local config file.
- **Category** - the pre-2019 name for the same idea, stored in
  `sharedconfig.vdf`. Depressurizer wrote these. Modern Steam ignores them.
- **Dynamic collection** - a collection defined by a filter (`filterSpec`) rather
  than a list of appids. Steam recomputes its membership; nothing may write to it.
- **Built-in collection** - `favorite` and `hidden`, which Steam creates itself
  and which steamshelf never touches.
- **Cloud config namespace** - a keyed blob store per user. Namespace 1 holds user
  settings, including collections. Namespace 3 exists and is unused here.
- **Entry** - one key/value pair in a namespace. Collections use keys shaped
  `user-collections.<id>`, with a JSON string value.
- **Namespace version** - a monotonic counter for a whole namespace. Every
  successful upload returns the next one.
- **CM (Connection Manager)** - a Steam server that speaks the client protocol.
  Reachable over websockets. The only route to `CloudConfigStore`.
- **EMsg** - Steam's message type enum. The high bit (`0x80000000`) set on the
  wire means the message carries a protobuf header.
- **Unified service / service method** - RPC over the CM, addressed by a job name
  like `CloudConfigStore.Download#1`.
- **Refresh token** - long-lived (months) JWT from login. Logs on to a CM and
  mints access tokens. Stored on disk.
- **Access token** - short-lived (about a day) JWT for Web API calls.
- **Steam Guard** - second factor. Either a code (email or authenticator) or a
  "device confirmation" the user approves in the mobile app.
- **appid** - the integer Steam identifies an app by.
- **Deck compatibility** - Valve's verdict for a game on Steam Deck: `Verified`,
  `Playable`, `Unsupported`, or `Unknown` if untested.

## steamshelf concepts

- **Family** - a category dimension: `hltb`, `platform`, `rating`, `deck`, `year`.
  Each produces zero or more collections for a game.
- **Managed collection** - one whose name starts with an active family's prefix.
  steamshelf reads these to work out what is already filed.
- **Producible collection** - a managed collection whose name the current config
  could itself generate. Only these are ever written to. See
  [collections/naming-and-ownership.md](collections/naming-and-ownership.md).
- **Uncategorized** - a game missing at least one *active family*, not a game in
  zero collections. This is what makes "buy a game, re-run" cheap.
- **Plan** - the computed set of per-game changes, before anything is written.
- **retry_later** - games whose lookup failed transiently. They keep their current
  categories and are picked up by the next run.
- **Lode** - this documentation repository.
