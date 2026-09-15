"""Thin HTTP helpers shared by the Steam and HowLongToBeat clients."""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Any

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


class HttpError(RuntimeError):
    def __init__(self, status: int, url: str, body: str, headers: dict[str, str]):
        super().__init__(f"HTTP {status} for {url}: {body[:200]}")
        self.status = status
        self.url = url
        self.body = body
        self.headers = headers


class Response:
    def __init__(self, status: int, headers: dict[str, str], body: bytes):
        self.status = status
        self.headers = headers
        self.body = body

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


def _decompress(raw: bytes, encoding: str) -> bytes:
    if encoding == "gzip":
        return gzip.decompress(raw)
    if encoding == "deflate":
        return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def request(
    url: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    data: bytes | None = None,
    json_body: Any = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    retries: int = 3,
) -> Response:
    if params:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{urllib.parse.urlencode(params)}"

    hdrs = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})

    last: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = _decompress(resp.read(), resp.headers.get("Content-Encoding", ""))
                return Response(resp.status, dict(resp.headers), raw)
        except urllib.error.HTTPError as exc:
            body = _decompress(exc.read(), exc.headers.get("Content-Encoding", ""))
            err = HttpError(exc.code, url, body.decode("utf-8", "replace"), dict(exc.headers))
            # 429 and 5xx are worth another go; everything else is the caller's problem.
            if exc.code not in (429, 500, 502, 503, 504) or attempt == retries - 1:
                raise err from None
            last = err
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == retries - 1:
                raise
            last = exc
        time.sleep(1.5 * (attempt + 1))

    raise last if last else RuntimeError("unreachable")


def get_json(url: str, **kwargs: Any) -> Any:
    return request(url, **kwargs).json()


def post_form(url: str, fields: dict[str, Any], **kwargs: Any) -> Response:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    headers.update(kwargs.pop("headers", {}))
    return request(url, method="POST", data=body, headers=headers, **kwargs)
