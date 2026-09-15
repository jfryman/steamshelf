"""A very small protobuf codec.

steamshelf only needs a handful of Steam's protobuf messages, and the
well-known Python bindings for them (ValvePython/steam) pin ``protobuf<=3.20``,
which has no wheels for current Pythons.  Encoding the dozen fields we actually
touch by hand is less code than vendoring generated bindings, and it keeps the
package dependency-light.

Messages are plain dicts keyed by field number.  A schema maps field number to
a ``(name, kind, repeated)`` triple so the CM layer can speak in names.
"""

from __future__ import annotations

import struct
from typing import Any

VARINT = 0
FIXED64 = 1
LENGTH = 2
FIXED32 = 5

# Field kinds understood by the codec.
KIND_WIRE = {
    "varint": VARINT,
    "bool": VARINT,
    "int32": VARINT,
    "uint32": VARINT,
    "int64": VARINT,
    "uint64": VARINT,
    "fixed32": FIXED32,
    "fixed64": FIXED64,
    "string": LENGTH,
    "bytes": LENGTH,
    "message": LENGTH,
}


def encode_varint(value: int) -> bytes:
    if value < 0:
        # Protobuf sign-extends negative varints to 64 bits.
        value += 1 << 64
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def decode_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def _encode_field(number: int, kind: str, value: Any, sub_schema: Any) -> bytes:
    wire = KIND_WIRE[kind]
    head = encode_varint((number << 3) | wire)
    if kind == "bool":
        return head + encode_varint(1 if value else 0)
    if wire == VARINT:
        return head + encode_varint(int(value))
    if kind == "fixed32":
        return head + struct.pack("<I", value & 0xFFFFFFFF)
    if kind == "fixed64":
        return head + struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF)
    if kind == "string":
        payload = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    elif kind == "bytes":
        payload = bytes(value)
    else:  # message
        payload = encode(value, sub_schema)
    return head + encode_varint(len(payload)) + payload


def encode(message: dict[str, Any], schema: dict[int, tuple]) -> bytes:
    """Serialize ``message`` (keyed by field name) using ``schema``."""
    by_name = {spec[0]: (number, spec) for number, spec in schema.items()}
    out = bytearray()
    # Protobuf does not require ordering, but Steam's own clients emit fields in
    # ascending field-number order and matching that keeps captures comparable.
    for name in sorted(message, key=lambda n: by_name[n][0] if n in by_name else 1 << 30):
        if name not in by_name:
            raise KeyError(f"unknown field {name!r} for schema")
        value = message[name]
        if value is None:
            continue
        number, spec = by_name[name]
        kind = spec[1]
        repeated = len(spec) > 2 and spec[2]
        sub = spec[3] if len(spec) > 3 else None
        if repeated:
            for item in value:
                out += _encode_field(number, kind, item, sub)
        else:
            out += _encode_field(number, kind, value, sub)
    return bytes(out)


def decode(buf: bytes, schema: dict[int, tuple]) -> dict[str, Any]:
    """Parse ``buf`` into a dict keyed by field name; unknown fields are dropped."""
    out: dict[str, Any] = {}
    pos = 0
    end = len(buf)
    while pos < end:
        tag, pos = decode_varint(buf, pos)
        number, wire = tag >> 3, tag & 0x07
        if wire == VARINT:
            raw, pos = decode_varint(buf, pos)
        elif wire == FIXED64:
            raw = struct.unpack_from("<Q", buf, pos)[0]
            pos += 8
        elif wire == FIXED32:
            raw = struct.unpack_from("<I", buf, pos)[0]
            pos += 4
        elif wire == LENGTH:
            size, pos = decode_varint(buf, pos)
            raw = buf[pos : pos + size]
            pos += size
        else:
            raise ValueError(f"unsupported wire type {wire} for field {number}")

        spec = schema.get(number)
        if spec is None:
            continue
        name, kind = spec[0], spec[1]
        repeated = len(spec) > 2 and spec[2]
        sub = spec[3] if len(spec) > 3 else None

        if kind == "bool":
            value: Any = bool(raw)
        elif kind == "string":
            value = raw.decode("utf-8", "replace")
        elif kind == "message":
            value = decode(raw, sub)
        elif kind in ("int32", "int64") and isinstance(raw, int):
            # Reinterpret the sign-extended varint.
            value = raw - (1 << 64) if raw >= 1 << 63 else raw
        else:
            value = raw

        if repeated:
            out.setdefault(name, []).append(value)
        else:
            out[name] = value
    return out
