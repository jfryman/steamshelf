"""Where steamshelf keeps its token, cache and config."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import auth


def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default)


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "steamshelf"
CACHE_DIR = _xdg("XDG_CACHE_HOME", ".cache") / "steamshelf"
TOKEN_PATH = CONFIG_DIR / "token.json"
CONFIG_PATH = CONFIG_DIR / "config.toml"


class SessionError(RuntimeError):
    pass


@dataclass
class Session:
    steamid: int
    account_name: str
    refresh_token: str
    access_token: str = ""
    access_token_expires: int = 0
    _dirty: bool = field(default=False, repr=False)

    @property
    def steamid3(self) -> int:
        """The 32-bit account id, which is what Steam's userdata folders use."""
        return self.steamid & 0xFFFFFFFF

    def web_token(self) -> str:
        """A valid web API access token, renewed from the refresh token if stale."""
        if self.access_token and self.access_token_expires > time.time() + 300:
            return self.access_token
        self.access_token = auth.access_token_for(self.refresh_token, self.steamid)
        self.access_token_expires = auth.token_expiry(self.access_token)
        self._dirty = True
        self.save()
        return self.access_token

    def save(self, path: Path = TOKEN_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "steamid": self.steamid,
            "account_name": self.account_name,
            "refresh_token": self.refresh_token,
            "access_token": self.access_token,
            "access_token_expires": self.access_token_expires,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n")
        os.chmod(tmp, 0o600)
        tmp.replace(path)
        self._dirty = False


def load(path: Path = TOKEN_PATH) -> Session:
    if not path.exists():
        raise SessionError("not logged in yet - run `steamshelf login`")
    data = json.loads(path.read_text())
    session = Session(
        steamid=int(data["steamid"]),
        account_name=data.get("account_name", ""),
        refresh_token=data["refresh_token"],
        access_token=data.get("access_token", ""),
        access_token_expires=int(data.get("access_token_expires", 0)),
    )
    if auth.token_expiry(session.refresh_token) < time.time():
        raise SessionError("the stored Steam token has expired - run `steamshelf login`")
    return session


def store(result: auth.LoginResult) -> Session:
    session = Session(
        steamid=result.steamid,
        account_name=result.account_name,
        refresh_token=result.refresh_token,
        access_token=result.access_token,
        access_token_expires=auth.token_expiry(result.access_token),
    )
    session.save()
    return session
