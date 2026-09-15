# Steam Auth

Getting a token that can both call the Web API and log on to a CM, without ever
storing a password.

```mermaid
flowchart LR
    OP["1Password (op CLI)"] -->|account, password| L["auth.login()"]
    L -->|"IAuthenticationService"| SW["Steam Web"]
    SW -->|refresh token| T["~/.config/steamshelf/token.json"]
    T -->|"GenerateAccessTokenForApp"| A["access token (~1 day)"]
    A --> W["Web API: GetOwnedGames"]
    T --> C["CM logon"]
```

## Files

| File | Contents |
|---|---|
| [credential-login.md](credential-login.md) | The login flow and Steam Guard |
| [token-lifecycle.md](token-lifecycle.md) | What is stored, renewed and expired |
| [onepassword.md](onepassword.md) | How credentials are read |

Related: [../cm/frame-protocol.md](../cm/frame-protocol.md)
