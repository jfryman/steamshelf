"""Steam credentials, read from 1Password via the ``op`` CLI."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

DEFAULT_ITEM = "Steam"


class CredentialError(RuntimeError):
    pass


@dataclass(frozen=True)
class Credentials:
    account_name: str
    password: str
    totp_secret: str | None = None


def _op(*args: str) -> str:
    if shutil.which("op") is None:
        raise CredentialError(
            "the 1Password CLI ('op') is not on PATH; install it or pass "
            "--account-name/--password-env"
        )
    proc = subprocess.run(
        ["op", *args], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or proc.stdout.strip()
        raise CredentialError(f"`op {' '.join(args)}` failed: {stderr}")
    return proc.stdout


def load(item: str = DEFAULT_ITEM, vault: str | None = None) -> Credentials:
    """Read account name, password and (if present) a TOTP secret from 1Password.

    ``item`` may be an item name, UUID or a full ``op://`` reference.
    """
    args = ["item", "get", item, "--format", "json"]
    if vault:
        args += ["--vault", vault]
    try:
        data = json.loads(_op(*args))
    except json.JSONDecodeError as exc:
        raise CredentialError(f"could not parse 1Password output for {item!r}") from exc

    username = password = totp = None
    for field in data.get("fields", []):
        purpose = field.get("purpose")
        label = (field.get("label") or "").lower()
        value = field.get("value")
        if not value:
            continue
        if purpose == "USERNAME" or label in ("username", "account name"):
            username = username or value
        elif purpose == "PASSWORD" or label == "password":
            password = password or value
        elif field.get("type") == "OTP" or label in ("one-time password", "totp"):
            # `op` returns the current 6-digit code here, not the shared secret.
            totp = totp or value

    if not username or not password:
        raise CredentialError(
            f"1Password item {item!r} is missing a username or password field"
        )
    return Credentials(account_name=username, password=password, totp_secret=totp)


def current_totp(item: str = DEFAULT_ITEM, vault: str | None = None) -> str | None:
    """Ask ``op`` for a freshly generated one-time code, if the item has one."""
    args = ["item", "get", item, "--otp"]
    if vault:
        args += ["--vault", vault]
    try:
        code = _op(*args).strip()
    except CredentialError:
        return None
    return code or None
