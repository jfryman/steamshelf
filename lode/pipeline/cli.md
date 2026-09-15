# CLI

`src/steamshelf/cli.py`. `argparse`, no third-party CLI framework.

## Commands

| Command | Purpose |
|---|---|
| `login` | 1Password -> Steam login -> stored refresh token |
| `status` | account, token path, config path, cache counts, Steam running? |
| `plan` | dry run |
| `apply` | plan, then write |
| `collections` | list collections, with `managed` / `dynamic` / `built-in` marks |
| `backup` | raw namespace dump |
| `config` | write or show `~/.config/steamshelf/config.toml` |
| `cache` | per-scope counts, `--clear` |

## Shared flags on plan/apply

| Flag | Effect |
|---|---|
| `--all` | reconsider every owned game |
| `--app APPID` | only this app, repeatable - the fast way to test a rule change |
| `--limit N` | stop after N games |
| `--source cloud\|local` | where existing collections are read from (default cloud) |
| `--store-delay` / `--hltb-delay` | pacing, in seconds |
| `-q` | suppress per-game progress |
| `-y` / `-v` | `apply` only: skip confirmation / list every game's changes |

`--app` is the development loop. `--app 70 -v` exercises the entire path -
login, CM, scrape, plan, upload - in seconds.

## Error style

Expected failures return `1` with a single `steamshelf: <message>` line on stderr,
never a traceback. The exception types that get this treatment are
`session.SessionError`, `store.StoreError`, `auth.AuthError` and
`credentials.CredentialError`; each carries a message written for a user, not a
developer - `"not logged in yet - run `steamshelf login`"` rather than
`FileNotFoundError`.

`KeyboardInterrupt` exits `130` with `Interrupted.`, which is safe at any point:
nothing is written until the upload step.

## Config

TOML at `~/.config/steamshelf/config.toml`, all keys optional. Note the structure
gotcha: family toggles live under `[categories.enable]`, not as bare keys in
`[categories]`, because `hltb = true` and `[categories.hltb]` cannot coexist in
TOML.

Related: [selection-and-planning.md](selection-and-planning.md),
[apply-and-safety.md](apply-and-safety.md)
