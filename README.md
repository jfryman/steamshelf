# steamshelf

A command line tool that files uncategorized Steam games into collections, using

- **How long it takes to beat**, from [HowLongToBeat](https://howlongtobeat.com)
- **The platforms it runs on**, from the Steam storefront, plus Steam Deck compatibility
- **Its overall review score**, from Steam's own review summary

It is a spiritual successor to [Depressurizer](https://github.com/Depressurizer/Depressurizer),
which is Windows-only and edits `sharedconfig.vdf` — a file modern Steam no
longer stores categories in. steamshelf logs in to your account and writes the
collections Steam actually uses today, so it works on Linux and macOS too.

The default collection names match Depressurizer's, so if you have used it
before, steamshelf extends the collections you already have:

```
(HLTB) 10-20        (Platform) Linux        (Score) Very Positive       (Deck) Verified
```

## Install

```sh
git clone https://github.com/jfryman/steamshelf ~/repo/src/github.com/jfryman/steamshelf
cd ~/repo/src/github.com/jfryman/steamshelf
python3 -m venv .venv && .venv/bin/pip install -e .
```

Requires Python 3.11+ and the [1Password CLI](https://developer.1password.com/docs/cli/)
(`op`) signed in to the account holding your Steam login.

## Use

```sh
steamshelf login     # reads your Steam password from 1Password, saves a token
steamshelf plan      # dry run: show exactly what would change
steamshelf apply     # write the collections to your Steam account
```

`login` needs to happen once; Steam's refresh token is good for months and is
stored mode-0600 in `~/.config/steamshelf/token.json`. If the account uses Steam
Guard you will be asked to approve the login in the mobile app, or to type in an
emailed code.

`plan` and `apply` only look at games that are missing at least one category
family — that is what "uncategorized" means here, so buying a game and re-running
files just that one. `--all` recategorizes the whole library.

Useful flags:

| Flag | Effect |
| --- | --- |
| `--all` | recategorize every owned game |
| `--app APPID` | only this app (repeatable), handy for testing a rule change |
| `--limit N` | stop after N games |
| `--source local` | read existing collections from the local Steam client mirror instead of the cloud |
| `-y` | `apply` without the confirmation prompt |

Other commands: `steamshelf status`, `steamshelf collections`,
`steamshelf config`, `steamshelf cache --clear`.

## Configuration

`steamshelf config` writes an annotated `~/.config/steamshelf/config.toml`.
You can change the 1Password item, turn category families on and off, rename the
prefixes, pick which HowLongToBeat figure to bucket on (`main`, `main_extra`,
`completionist`, `all`), and redefine the time buckets:

```toml
[categories.hltb]
style = "main"
buckets = [
    [5,      " 0-5"],
    [10,     " 5-10"],
    [20,     "10-20"],
    [50,     "20-50"],
    [100000, "50+"],
]
```

A `year` family (`(Year) 2019`) is available but off by default.

## How it works

Steam moved library categories out of `sharedconfig.vdf` and into *collections*,
stored in cloud config namespace 1 as JSON blobs keyed `user-collections.<id>`.
That store is served by `CloudConfigStore`, which — unlike most of Steam's
Web API — is not exposed on `api.steampowered.com`; it is only reachable over a
connection manager (CM) session.

So steamshelf does two things Depressurizer does not:

1. **Logs in the modern way.** `IAuthenticationService` over plain HTTPS: fetch
   an RSA key, encrypt the password, begin a session, satisfy Steam Guard, poll
   for a refresh token.
2. **Talks to a CM.** A small websocket client (`steamshelf/cm.py`) logs on with
   that refresh token and calls `CloudConfigStore.Download#1` /
   `Upload#1`. Message schemas are hand-written against the protobuf descriptors
   Valve ships inside `steamclient.so`, encoded by a ~150-line protobuf codec
   (`steamshelf/wire.py`), which avoids depending on bindings that pin an
   ancient `protobuf` release.

Metadata comes from the storefront one app at a time — Valve exposes no bulk
endpoint to the open web — so results are cached in
`~/.cache/steamshelf/metadata.sqlite3` and requests are paced. The first full
run over a large library takes a while; later runs are fast.

HowLongToBeat has no public API either. steamshelf does what the site's own
search box does: ask `/api/search/site/init` for a short-lived token, then POST
the search with it. Matches are made on a normalized title, with sequel numbers
required to agree, and each match records a confidence score.

## Caveats

- Dynamic (filter-based) collections and Steam's built-in `Favorites` / `Hidden`
  are never touched.
- `apply` re-reads collections immediately before writing, but Steam's client
  can still overwrite a collection it had cached. Closing Steam first is the
  safest way to run it.
- HowLongToBeat's search endpoint is undocumented and rejects roughly one
  request in ten; steamshelf retries, but a game that finds no match lands in
  `(HLTB) Unknown` rather than failing the run.

## Development

```sh
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest          # unit tests, no network
.venv/bin/ruff check src/
```

`steamshelf backup` writes a raw namespace dump you can keep; `apply` takes one
automatically into `~/.cache/steamshelf/backups/` before every upload.

## License

MIT
