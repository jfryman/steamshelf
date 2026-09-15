# 1Password Credentials

`src/steamshelf/credentials.py`. Shells out to the `op` CLI; no SDK, no vault
file parsing.

```python
op item get <item> --format json [--vault <vault>]
```

The item is resolved by name, UUID or `op://` reference, defaulting to `"Steam"`
and configurable under `[onepassword]` in the config file.

## Field mapping

Fields are matched by 1Password's `purpose` first and label second, because a
hand-made item may not set `purpose`:

| Wanted | Matched on |
|---|---|
| account name | `purpose == "USERNAME"`, or label `username` / `account name` |
| password | `purpose == "PASSWORD"`, or label `password` |
| one-time code | `type == "OTP"`, or label `one-time password` / `totp` |

## Gotcha: `op` returns codes, not secrets

For an OTP field, `op item get --format json` yields the **current six-digit
code**, not the shared secret. `current_totp()` exists to fetch a fresh one via
`op item get --otp` at the moment it is needed, since a code read earlier in the
run may already have rotated.

If the item has no OTP field at all - which is the common case for a Steam account
using the mobile app - login falls through to device confirmation. See
[credential-login.md](credential-login.md).

## Failure modes

- `op` missing from `PATH` -> a clear message naming the CLI.
- `op` not signed in -> its stderr is surfaced verbatim; it is more useful than
  anything we could paraphrase.
- Item found but missing username or password -> named explicitly, since a
  partially filled item is a common setup mistake.

Related: [credential-login.md](credential-login.md)
