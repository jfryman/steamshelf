"""Steam's modern credential login (IAuthenticationService), over plain HTTPS.

The flow is:

1. ``GetPasswordRSAPublicKey``   -> a short-lived RSA key for the account
2. ``BeginAuthSessionViaCredentials`` -> a session plus the Steam Guard methods
   the account allows
3. ``UpdateAuthSessionWithSteamGuardCode`` for email/app codes, or nothing at
   all when the account uses mobile "approve this login" confirmation
4. ``PollAuthSessionStatus``     -> a refresh token

The refresh token is what gets stored; access tokens are minted from it on
demand and last about a day.  A ``SteamClient`` platform token is requested
because the same token has to log the CM connection in, which is how
collections get written.
"""

from __future__ import annotations

import base64
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import http

API = "https://api.steampowered.com"

PLATFORM_STEAM_CLIENT = 1
OS_TYPE_LINUX = -203  # k_EOSTypeLinuxUnknown; Steam accepts any plausible value.

GUARD_NONE = 0
GUARD_UNKNOWN = 1
GUARD_EMAIL_CODE = 2
GUARD_DEVICE_CODE = 3
GUARD_DEVICE_CONFIRMATION = 4
GUARD_EMAIL_CONFIRMATION = 5
GUARD_MACHINE_TOKEN = 6

GUARD_NAMES = {
    GUARD_EMAIL_CODE: "a code emailed to you",
    GUARD_DEVICE_CODE: "the code from your Steam Mobile Authenticator",
    GUARD_DEVICE_CONFIRMATION: "approval in the Steam mobile app",
    GUARD_EMAIL_CONFIRMATION: "confirmation from the link in your email",
}

# https://partner.steamgames.com/doc/api/steam_api#EResult
ERESULT_NAMES = {
    1: "OK",
    5: "InvalidPassword",
    15: "AccessDenied",
    20: "ServiceUnavailable",
    65: "TwoFactorCodeMismatch",
    84: "RateLimitExceeded",
    85: "AccountLoginDeniedNeedTwoFactor",
    88: "FailedToDecryptRefreshToken",
}


class AuthError(RuntimeError):
    pass


def _eresult(resp: http.Response) -> int:
    return int(resp.headers.get("x-eresult", 0) or 0)


def _describe(resp: http.Response) -> str:
    code = _eresult(resp)
    name = ERESULT_NAMES.get(code, f"EResult {code}")
    detail = resp.headers.get("x-error_message")
    return f"{name}: {detail}" if detail else name


def _service_post(method: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    fields: dict[str, Any] = {"input_json": json.dumps(payload)}
    if token:
        fields["access_token"] = token
    resp = http.post_form(f"{API}/IAuthenticationService/{method}/v1/", fields)
    body = resp.json().get("response", {})
    if not body and _eresult(resp) not in (0, 1):
        raise AuthError(f"{method} failed - {_describe(resp)}")
    return body


def _encrypt_password(password: str, modulus_hex: str, exponent_hex: str) -> str:
    """RSA PKCS#1 v1.5 encrypt, which is all Steam's login key is used for."""
    modulus = int(modulus_hex, 16)
    exponent = int(exponent_hex, 16)
    size = (modulus.bit_length() + 7) // 8
    message = password.encode("utf-8")
    pad_len = size - len(message) - 3
    if pad_len < 8:
        raise AuthError("password is too long for Steam's RSA key")

    padding = bytearray()
    while len(padding) < pad_len:
        padding.extend(b for b in os.urandom(pad_len * 2) if b)  # PS must be nonzero
    block = b"\x00\x02" + bytes(padding[:pad_len]) + b"\x00" + message
    cipher = pow(int.from_bytes(block, "big"), exponent, modulus)
    return base64.b64encode(cipher.to_bytes(size, "big")).decode("ascii")


@dataclass
class LoginResult:
    steamid: int
    account_name: str
    refresh_token: str
    access_token: str


def login(
    account_name: str,
    password: str,
    *,
    device_name: str = "steamshelf",
    code_provider: Callable[[int, str], str] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> LoginResult:
    """Log in and return a SteamClient-platform refresh token.

    ``code_provider`` is called with ``(guard_type, hint)`` when Steam wants a
    Steam Guard code; ``on_status`` receives human-readable progress lines.
    """
    say = on_status or (lambda _msg: None)

    key = http.get_json(
        f"{API}/IAuthenticationService/GetPasswordRSAPublicKey/v1/",
        params={"account_name": account_name},
    )["response"]
    if "publickey_mod" not in key:
        raise AuthError(f"Steam did not return a login key for {account_name!r}")

    begin = _service_post(
        "BeginAuthSessionViaCredentials",
        {
            "account_name": account_name,
            "encrypted_password": _encrypt_password(
                password, key["publickey_mod"], key["publickey_exp"]
            ),
            "encryption_timestamp": key["timestamp"],
            "remember_login": True,
            "platform_type": PLATFORM_STEAM_CLIENT,
            "persistence": 1,  # k_ESessionPersistence_Persistent
            "device_details": {
                "device_friendly_name": device_name,
                "platform_type": PLATFORM_STEAM_CLIENT,
                "os_type": OS_TYPE_LINUX,
                "gaming_device_type": 1,  # Unknown/PC
            },
        },
    )
    if "client_id" not in begin:
        raise AuthError(
            "Steam rejected the credentials (wrong password, or the account is "
            "rate-limited after too many attempts)"
        )

    client_id = begin["client_id"]
    request_id = begin["request_id"]
    steamid = int(begin.get("steamid", 0))
    interval = float(begin.get("interval", 5.0))

    confirmations = [
        int(c.get("confirmation_type", GUARD_UNKNOWN))
        for c in begin.get("allowed_confirmations", [])
    ]
    hint = begin.get("extended_error_message") or ""
    for conf in begin.get("allowed_confirmations", []):
        if conf.get("associated_message"):
            hint = conf["associated_message"]

    code_types = [c for c in confirmations if c in (GUARD_EMAIL_CODE, GUARD_DEVICE_CODE)]
    if code_types and GUARD_DEVICE_CONFIRMATION not in confirmations:
        guard_type = code_types[0]
        if code_provider is None:
            raise AuthError(
                f"this account needs Steam Guard ({GUARD_NAMES.get(guard_type, 'a code')}) "
                "but no way to ask for it was provided"
            )
        code = code_provider(guard_type, hint).strip()
        updated = _service_post(
            "UpdateAuthSessionWithSteamGuardCode",
            {
                "client_id": client_id,
                "steamid": steamid,
                "code": code,
                "code_type": guard_type,
            },
        )
        if updated.get("agreement_session_url"):
            say("Steam wants you to visit: " + updated["agreement_session_url"])
    elif GUARD_DEVICE_CONFIRMATION in confirmations:
        say("Waiting for you to approve this login in the Steam mobile app...")
    elif GUARD_EMAIL_CONFIRMATION in confirmations:
        say("Waiting for you to confirm this login from the link Steam emailed you...")

    deadline = time.time() + 180
    while True:
        poll = _service_post(
            "PollAuthSessionStatus", {"client_id": client_id, "request_id": request_id}
        )
        if poll.get("refresh_token"):
            return LoginResult(
                steamid=steamid or int(poll.get("steamid", 0)),
                account_name=poll.get("account_name") or account_name,
                refresh_token=poll["refresh_token"],
                access_token=poll.get("access_token", ""),
            )
        if poll.get("had_remote_interaction") is False and time.time() > deadline:
            raise AuthError("timed out waiting for Steam Guard approval")
        if time.time() > deadline:
            raise AuthError("timed out waiting for Steam Guard approval")
        if poll.get("new_client_id"):
            client_id = poll["new_client_id"]
        time.sleep(interval)


def access_token_for(refresh_token: str, steamid: int) -> str:
    """Mint a fresh web access token from a stored refresh token."""
    body = _service_post(
        "GenerateAccessTokenForApp",
        {"refresh_token": refresh_token, "steamid": steamid, "renewal_type": 0},
    )
    token = body.get("access_token")
    if not token:
        raise AuthError("could not renew the Steam access token; run `steamshelf login` again")
    return token


def token_expiry(jwt: str) -> int:
    """Return the ``exp`` claim of a Steam JWT, or 0 if it cannot be read."""
    try:
        payload = jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return int(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except Exception:
        return 0
