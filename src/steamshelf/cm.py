"""A minimal Steam CM (connection manager) client, just enough for collections.

Steam's collection store, ``CloudConfigStore``, is not exposed on
``api.steampowered.com`` -- it is a client-only service reachable over the CM
connection.  The websocket transport is the easy one: TLS handles encryption, so
each websocket frame is simply

    uint32 emsg | 0x80000000
    uint32 header_length
    CMsgProtoBufHeader
    body

This module connects, logs on with a refresh token from :mod:`steamshelf.auth`,
and makes unified-service calls.  Message schemas are hand-written against the
descriptors Valve ships inside ``steamclient.so``.
"""

from __future__ import annotations

import gzip
import random
import struct
import threading
import time
from typing import Any

from . import http, wire

PROTO_MASK = 0x80000000

EMSG_MULTI = 1
EMSG_SERVICE_METHOD_RESPONSE = 147
EMSG_SERVICE_METHOD_CALL_FROM_CLIENT = 151
EMSG_CLIENT_HEARTBEAT = 703
EMSG_CLIENT_LOGON_RESPONSE = 751
EMSG_CLIENT_LOGGED_OFF = 757
EMSG_CLIENT_LOGON = 5514
EMSG_CLIENT_HELLO = 9805

PROTOCOL_VERSION = 65580
CLIENT_PACKAGE_VERSION = 1771
OS_TYPE_LINUX_UNKNOWN = -203
ANONYMOUS_STEAMID = 0x0110000100000000

# --- message schemas (field number -> (name, kind[, repeated[, submessage]])) ---

HEADER = {
    1: ("steamid", "fixed64"),
    2: ("client_sessionid", "int32"),
    10: ("jobid_source", "fixed64"),
    11: ("jobid_target", "fixed64"),
    12: ("target_job_name", "string"),
    13: ("eresult", "int32"),
    14: ("error_message", "string"),
    32: ("realm", "uint32"),
}

CLIENT_LOGON = {
    1: ("protocol_version", "uint32"),
    3: ("cell_id", "uint32"),
    5: ("client_package_version", "uint32"),
    6: ("client_language", "string"),
    7: ("client_os_type", "int32"),
    8: ("should_remember_password", "bool"),
    22: ("client_supplied_steam_id", "fixed64"),
    30: ("machine_id", "bytes"),
    50: ("account_name", "string"),
    96: ("machine_name", "string"),
    100: ("client_instance_id", "uint64"),
    102: ("supports_rate_limit_response", "bool"),
    108: ("access_token", "string"),
}

CLIENT_LOGON_RESPONSE = {
    1: ("eresult", "int32"),
    3: ("heartbeat_seconds", "int32"),
    7: ("cell_id", "uint32"),
    10: ("eresult_extended", "int32"),
    20: ("client_supplied_steamid", "fixed64"),
}

MULTI = {1: ("size_unzipped", "uint32"), 2: ("message_body", "bytes")}

CLOUD_ENTRY = {
    1: ("key", "string"),
    2: ("is_deleted", "bool"),
    3: ("value", "string"),
    4: ("timestamp", "fixed32"),
    5: ("version", "uint64"),
}
CLOUD_NAMESPACE_DATA = {
    1: ("enamespace", "uint32"),
    2: ("version", "uint64"),
    3: ("entries", "message", True, CLOUD_ENTRY),
    4: ("horizon", "uint64"),
}
CLOUD_NAMESPACE_VERSION = {1: ("enamespace", "uint32"), 2: ("version", "uint64")}
CLOUD_DOWNLOAD_REQUEST = {1: ("versions", "message", True, CLOUD_NAMESPACE_VERSION)}
CLOUD_DOWNLOAD_RESPONSE = {1: ("data", "message", True, CLOUD_NAMESPACE_DATA)}
CLOUD_UPLOAD_REQUEST = {1: ("data", "message", True, CLOUD_NAMESPACE_DATA)}
CLOUD_UPLOAD_RESPONSE = {1: ("versions", "message", True, CLOUD_NAMESPACE_VERSION)}

ERESULT_NAMES = {
    1: "OK",
    5: "InvalidPassword",
    6: "LoggedInElsewhere",
    15: "AccessDenied",
    16: "Timeout",
    20: "ServiceUnavailable",
    24: "DataCorruption",
    84: "RateLimitExceeded",
}


class CMError(RuntimeError):
    def __init__(self, message: str, eresult: int = 0):
        if eresult:
            message = f"{message} ({ERESULT_NAMES.get(eresult, f'EResult {eresult}')})"
        super().__init__(message)
        self.eresult = eresult


def _servers(limit: int = 8) -> list[str]:
    data = http.get_json(
        "https://api.steampowered.com/ISteamDirectory/GetCMListForConnect/v1/",
        params={"cellid": 0, "cmtype": "websockets", "format": "json"},
    )
    servers = data["response"]["serverlist"]
    servers.sort(key=lambda s: s.get("wtd_load", 1e9))
    return [s["endpoint"] for s in servers[:limit]]


class CMClient:
    """Logs on to a CM over websockets and issues unified service calls."""

    def __init__(self, *, timeout: float = 30.0):
        self._timeout = timeout
        self._ws: Any = None
        self._lock = threading.Lock()
        self._jobid = random.randint(1, 1 << 30)
        self.steamid = 0
        self.session_id = 0
        self.cell_id = 0

    # -- transport -----------------------------------------------------------

    def connect(self) -> None:
        try:
            import websocket  # noqa: PLC0415  (optional-ish, heavy import)
        except ImportError as exc:  # pragma: no cover
            raise CMError(
                "the 'websocket-client' package is required to talk to Steam's "
                "connection managers; install steamshelf's dependencies"
            ) from exc

        last: Exception | None = None
        for endpoint in _servers():
            try:
                self._ws = websocket.create_connection(
                    f"wss://{endpoint}/cmsocket/",
                    timeout=self._timeout,
                    origin="https://steamcommunity.com",
                    header={"User-Agent": http.USER_AGENT},
                )
                return
            except (TimeoutError, OSError, Exception) as exc:  # noqa: BLE001
                last = exc
        raise CMError(f"could not reach any Steam connection manager: {last}")

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            finally:
                self._ws = None

    def __enter__(self) -> CMClient:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _send(self, emsg: int, header: dict[str, Any], body: bytes) -> None:
        head = wire.encode(header, HEADER)
        frame = struct.pack("<II", emsg | PROTO_MASK, len(head)) + head + body
        with self._lock:
            self._ws.send_binary(frame)

    @staticmethod
    def _parse_frame(data: bytes) -> tuple[int, dict[str, Any], bytes] | None:
        """Split one CM frame.  Returns None for pre-protobuf messages.

        Steam still sends a few struct-framed messages (they lack the protobuf
        mask and carry a fixed binary header instead).  steamshelf needs none of
        them, and parsing one as protobuf yields garbage, so they are dropped.
        """
        if len(data) < 8 or not struct.unpack_from("<I", data, 0)[0] & PROTO_MASK:
            return None
        raw_emsg, head_len = struct.unpack_from("<II", data, 0)
        if head_len > len(data) - 8:
            return None
        return (
            raw_emsg & ~PROTO_MASK,
            wire.decode(data[8 : 8 + head_len], HEADER),
            data[8 + head_len :],
        )

    def _recv_raw(self) -> tuple[int, dict[str, Any], bytes] | None:
        data = self._ws.recv()
        if isinstance(data, str):  # pragma: no cover - CM speaks binary
            data = data.encode()
        return self._parse_frame(data)

    def _messages(self) -> Any:
        """Yield ``(emsg, header, body)``, flattening Multi envelopes."""
        pending: list[tuple[int, dict[str, Any], bytes]] = []
        while True:
            if pending:
                yield pending.pop(0)
                continue
            frame = self._recv_raw()
            if frame is None:
                continue
            emsg, header, body = frame
            if emsg != EMSG_MULTI:
                yield emsg, header, body
                continue
            multi = wire.decode(body, MULTI)
            payload = multi.get("message_body", b"")
            if multi.get("size_unzipped"):
                payload = gzip.decompress(payload)
            offset = 0
            while offset + 4 <= len(payload):
                (size,) = struct.unpack_from("<I", payload, offset)
                offset += 4
                chunk = payload[offset : offset + size]
                offset += size
                inner = self._parse_frame(chunk)
                if inner is not None:
                    pending.append(inner)

    # -- session -------------------------------------------------------------

    def logon(self, account_name: str, refresh_token: str, steamid: int) -> None:
        self._send(EMSG_CLIENT_HELLO, {}, wire.encode({"protocol_version": PROTOCOL_VERSION}, {1: ("protocol_version", "uint32")}))

        body = wire.encode(
            {
                "protocol_version": PROTOCOL_VERSION,
                "client_package_version": CLIENT_PACKAGE_VERSION,
                "client_language": "english",
                "client_os_type": OS_TYPE_LINUX_UNKNOWN,
                "should_remember_password": True,
                "client_supplied_steam_id": steamid,
                "account_name": account_name,
                "machine_name": "steamshelf",
                "client_instance_id": 0,
                "supports_rate_limit_response": True,
                "access_token": refresh_token,
            },
            CLIENT_LOGON,
        )
        self._send(EMSG_CLIENT_LOGON, {"steamid": steamid or ANONYMOUS_STEAMID, "client_sessionid": 0}, body)

        deadline = time.time() + self._timeout
        for emsg, header, payload in self._messages():
            if emsg == EMSG_CLIENT_LOGON_RESPONSE:
                resp = wire.decode(payload, CLIENT_LOGON_RESPONSE)
                eresult = resp.get("eresult", 0)
                if eresult != 1:
                    raise CMError("Steam refused the logon", eresult)
                self.steamid = resp.get("client_supplied_steamid") or header.get("steamid", steamid)
                self.session_id = header.get("client_sessionid", 0)
                self.cell_id = resp.get("cell_id", 0)
                self._start_heartbeat(max(int(resp.get("heartbeat_seconds", 9)), 1))
                return
            if emsg == EMSG_CLIENT_LOGGED_OFF:
                raise CMError("Steam logged us off during logon", header.get("eresult", 0))
            if time.time() > deadline:
                break
        raise CMError("timed out waiting for Steam's logon response")

    def _start_heartbeat(self, seconds: int) -> None:
        def beat() -> None:
            while self._ws is not None:
                time.sleep(seconds)
                try:
                    self._send(
                        EMSG_CLIENT_HEARTBEAT,
                        {"steamid": self.steamid, "client_sessionid": self.session_id},
                        b"",
                    )
                except Exception:  # noqa: BLE001 - connection is going away anyway
                    return

        threading.Thread(target=beat, daemon=True, name="steamshelf-heartbeat").start()

    # -- unified service calls ----------------------------------------------

    def call(
        self,
        method: str,
        request: dict[str, Any],
        request_schema: dict[int, tuple],
        response_schema: dict[int, tuple],
    ) -> dict[str, Any]:
        """Invoke ``Service.Method#1`` and return the decoded response."""
        self._jobid += 1
        jobid = self._jobid
        self._send(
            EMSG_SERVICE_METHOD_CALL_FROM_CLIENT,
            {
                "steamid": self.steamid,
                "client_sessionid": self.session_id,
                "jobid_source": jobid,
                "target_job_name": method,
            },
            wire.encode(request, request_schema),
        )

        deadline = time.time() + self._timeout
        for emsg, header, payload in self._messages():
            if emsg == EMSG_SERVICE_METHOD_RESPONSE and header.get("jobid_target") == jobid:
                eresult = header.get("eresult", 1)
                if eresult != 1:
                    raise CMError(
                        f"{method} failed: {header.get('error_message', '')}".strip(), eresult
                    )
                return wire.decode(payload, response_schema)
            if emsg == EMSG_CLIENT_LOGGED_OFF:
                raise CMError("Steam logged us off", header.get("eresult", 0))
            if time.time() > deadline:
                break
        raise CMError(f"timed out waiting for a response to {method}")

    # -- CloudConfigStore ----------------------------------------------------

    def download_namespace(self, enamespace: int = 1, since_version: int = 0) -> dict[str, Any]:
        resp = self.call(
            "CloudConfigStore.Download#1",
            {"versions": [{"enamespace": enamespace, "version": since_version}]},
            CLOUD_DOWNLOAD_REQUEST,
            CLOUD_DOWNLOAD_RESPONSE,
        )
        for data in resp.get("data", []):
            if data.get("enamespace") == enamespace:
                return data
        return {"enamespace": enamespace, "version": since_version, "entries": []}

    def upload_entries(
        self, entries: list[dict[str, Any]], enamespace: int = 1, version: int = 0
    ) -> int:
        """Write ``entries`` into the namespace; returns the new namespace version."""
        resp = self.call(
            "CloudConfigStore.Upload#1",
            {"data": [{"enamespace": enamespace, "version": version, "entries": entries}]},
            CLOUD_UPLOAD_REQUEST,
            CLOUD_UPLOAD_RESPONSE,
        )
        for ver in resp.get("versions", []):
            if ver.get("enamespace") == enamespace:
                return int(ver.get("version", 0))
        return 0
