# Token Lifecycle

`src/steamshelf/session.py`.

## What is stored

`~/.config/steamshelf/token.json`, written `0o600` via a temp file and atomic
rename:

```json
{
  "steamid": 76561198020885186,
  "account_name": "...",
  "refresh_token": "eyJ...",
  "access_token": "eyJ...",
  "access_token_expires": 1789591695
}
```

The password is never stored; it is read from 1Password at login time and
discarded.

## Two tokens, two jobs

| Token | Lifetime | Used for |
|---|---|---|
| refresh | months | CM logon (`CMsgClientLogon.access_token`), minting access tokens |
| access | ~1 day | Web API calls (`IPlayerService/GetOwnedGames`) |

```python
def web_token(self):
    if self.access_token and self.access_token_expires > time.time() + 300:
        return self.access_token
    self.access_token = auth.access_token_for(self.refresh_token, self.steamid)
    self.access_token_expires = auth.token_expiry(self.access_token)
    self.save()
    return self.access_token
```

The 300-second margin avoids a token expiring mid-run. Expiry is read from the
JWT's `exp` claim without verifying the signature - we are not the audience, we
just need the timestamp.

## SteamID forms

`steamid` is the 64-bit form. `steamid3` is `steamid & 0xFFFFFFFF`, the 32-bit
account id, which is what Steam's `userdata/<id>/` directories are named after.
Both are needed; do not conflate them.

## Expiry handling

`session.load()` refuses a refresh token whose `exp` has passed and tells the user
to run `steamshelf login` again, rather than failing deeper in with a confusing
CM or Web API error.

Related: [credential-login.md](credential-login.md)
